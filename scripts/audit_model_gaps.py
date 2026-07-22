"""Audit typed Pydantic models against their FEWS XSDs.

Two modes:
  - shallow (default): for each SPECS entry, compare the root
    complexType's direct fields against the model's fields.
  - deep (``--deep``): additionally traverse every field whose Python
    type is a FewsModel subclass (or list[FewsModel]) and cross-reference
    that nested model against its corresponding XSD complexType.

XSD type references are resolved across every schema in ``schemas/`` —
types declared in ``sharedTypes.xsd`` are reachable from every dependent.
"""
from __future__ import annotations

import re
import sys
import types
import typing
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree
from pydantic import BaseModel

from fews_agent.generators import SPECS


XS_NS = {"xs": "http://www.w3.org/2001/XMLSchema"}
SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "fews_agent" / "schemas"
_NS_RE = re.compile(r"\}(\w+)")


def _localname(el) -> str:
    m = _NS_RE.search(str(el.tag))
    return m.group(1) if m else ""


# ── Load every complex type across every schema, once ─────────────────

@dataclass
class XsdType:
    name: str
    source: str  # XSD filename
    elements: dict[str, str] = field(default_factory=dict)  # name -> type
    attributes: set[str] = field(default_factory=set)


def _walk_sequence(container, out_elements: dict[str, str]) -> None:
    """Collect direct <element> children, descending into nested
    <sequence>/<choice>. Ignores <group ref=...> and <any>."""
    for child in container:
        lname = _localname(child)
        if lname == "element" and child.get("name"):
            typ = child.get("type", "")
            out_elements[child.get("name")] = typ.split(":")[-1] if typ else ""
        elif lname in ("sequence", "choice"):
            _walk_sequence(child, out_elements)


def _parse_complex_type(ct, source: str) -> XsdType:
    name = ct.get("name") or ""
    xt = XsdType(name=name, source=source)
    for child in ct:
        lname = _localname(child)
        if lname in ("sequence", "choice"):
            _walk_sequence(child, xt.elements)
        elif lname == "complexContent":
            # extension-based: merge base + extension children
            for sub in child:
                if _localname(sub) == "extension":
                    # Note the base type; caller (caller's audit) can merge
                    # fields from the base complex type separately.
                    xt.attributes.add(f"__extends__:{sub.get('base','').split(':')[-1]}")
                    for e2 in sub:
                        if _localname(e2) in ("sequence", "choice"):
                            _walk_sequence(e2, xt.elements)
                        elif _localname(e2) == "attribute" and e2.get("name"):
                            xt.attributes.add(e2.get("name"))
        elif lname == "attribute" and child.get("name"):
            xt.attributes.add(child.get("name"))
    return xt


def _load_all_xsd_types() -> dict[str, XsdType]:
    """Global type registry keyed by complexType name (first-wins)."""
    out: dict[str, XsdType] = {}
    for path in sorted(SCHEMAS_DIR.glob("*.xsd")):
        try:
            tree = etree.parse(str(path))
        except etree.XMLSyntaxError:
            continue
        for ct in tree.getroot().findall("xs:complexType", XS_NS):
            name = ct.get("name")
            if not name or name in out:
                continue
            out[name] = _parse_complex_type(ct, path.name)
    return out


def _resolve_extensions(types_map: dict[str, XsdType]) -> None:
    """Merge fields of base types into types that extend them."""
    for xt in types_map.values():
        # Copy to avoid mutation during iteration
        extends = [a.split(":", 1)[1] for a in xt.attributes if a.startswith("__extends__:")]
        for base_name in extends:
            base = types_map.get(base_name)
            if base is not None:
                for k, v in base.elements.items():
                    xt.elements.setdefault(k, v)
                for a in base.attributes:
                    if not a.startswith("__extends__:"):
                        xt.attributes.add(a)
        # Drop the sentinel markers
        xt.attributes -= {a for a in xt.attributes if a.startswith("__extends__:")}


# ── Model introspection ───────────────────────────────────────────────

def _model_field_names(model_class: type) -> set[str]:
    """Field names including alias and dropped-underscore variants."""
    names: set[str] = set()
    for field_name, info in model_class.model_fields.items():
        names.add(field_name)
        if field_name.endswith("_"):
            names.add(field_name.rstrip("_"))
        if info.alias:
            names.add(info.alias)
    return names


def _unpack_type(annotation) -> list[type]:
    """Return any nested FewsModel classes inside an annotation. Handles
    Optional, Union, list[...], dict[...] and forward-ref strings."""
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    found: list[type] = []
    if origin is None:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            found.append(annotation)
        return found
    if origin in (list, dict, tuple, set, frozenset, types.UnionType, typing.Union):
        for a in args:
            found.extend(_unpack_type(a))
        return found
    # Covers generic aliases like Annotated[...]
    for a in args:
        found.extend(_unpack_type(a))
    return found


def _model_nested_types(model_class: type) -> dict[str, list[type]]:
    """For each field name, list nested FewsModel subclasses referenced
    in its annotation."""
    out: dict[str, list[type]] = {}
    for fname, info in model_class.model_fields.items():
        key = info.alias or fname.rstrip("_") if fname.endswith("_") and info.alias is None else (info.alias or fname)
        nested = _unpack_type(info.annotation)
        if nested:
            out[key] = nested
    return out


# ── XSD root lookup ───────────────────────────────────────────────────

def _xsd_for_input_key(input_key: str, output_relpath: Path) -> str | None:
    candidates = [
        f"{input_key}.xsd",
        f"{input_key[0].lower() + input_key[1:]}.xsd",
        f"{output_relpath.stem[0].lower() + output_relpath.stem[1:]}.xsd",
    ]
    for c in candidates:
        if (SCHEMAS_DIR / c).exists():
            return c
    return None


def _root_type_candidates(xsd_name: str) -> list[str]:
    """Top-level <xs:element> type references in the XSD (by complex-type
    name). Handles multi-root XSDs like parameters.xsd."""
    path = SCHEMAS_DIR / xsd_name
    if not path.exists():
        return []
    tree = etree.parse(str(path))
    out: list[str] = []
    for el in tree.getroot().findall("xs:element", XS_NS):
        typ = el.get("type", "")
        if typ:
            out.append(typ.split(":")[-1])
    return out


# ── Deep audit ────────────────────────────────────────────────────────

@dataclass
class DeepGap:
    path: str  # dotted path e.g. "parameters > parameterGroup > parameter"
    model_name: str
    xsd_type: str
    missing_elems: set[str] = field(default_factory=set)
    missing_attrs: set[str] = field(default_factory=set)

    @property
    def total(self) -> int:
        return len(self.missing_elems) + len(self.missing_attrs)


def _audit_deep(
    model_class: type,
    xsd_type_name: str,
    path: str,
    types_map: dict[str, XsdType],
    visited: set[tuple[str, str]],
    out: list[DeepGap],
) -> None:
    """Recursively audit a model against an XSD complex type."""
    key = (model_class.__name__, xsd_type_name)
    if key in visited:
        return
    visited.add(key)

    xt = types_map.get(xsd_type_name)
    if xt is None:
        return

    model_fields = _model_field_names(model_class)
    missing_elems = set(xt.elements) - model_fields
    missing_attrs = xt.attributes - model_fields
    if missing_elems or missing_attrs:
        out.append(DeepGap(
            path=path,
            model_name=model_class.__name__,
            xsd_type=xsd_type_name,
            missing_elems=missing_elems,
            missing_attrs=missing_attrs,
        ))

    # Recurse into nested typed fields whose XSD element has a type we know
    nested = _model_nested_types(model_class)
    for field_name, models in nested.items():
        child_xsd_type = xt.elements.get(field_name)
        if not child_xsd_type:
            continue
        for nested_cls in models:
            child_path = f"{path} > {field_name}"
            _audit_deep(nested_cls, child_xsd_type, child_path, types_map, visited, out)


# ── Shallow report (root-only, same as before) ───────────────────────

def _shallow_report() -> None:
    from fews_agent.schema import GenericXmlFile

    types_map = _load_all_xsd_types()
    _resolve_extensions(types_map)

    rows: list[tuple[str, int, int, set[str], set[str]]] = []
    for spec in SPECS:
        if spec.model_class is GenericXmlFile:
            continue
        xsd_name = _xsd_for_input_key(spec.input_key, spec.output_relpath)
        if not xsd_name:
            continue
        type_candidates = _root_type_candidates(xsd_name)
        if not type_candidates:
            continue
        model_fields = _model_field_names(spec.model_class)
        best = None
        for root_type in type_candidates:
            xt = types_map.get(root_type)
            if xt is None:
                continue
            missing_elems = set(xt.elements) - model_fields
            missing_attrs = xt.attributes - model_fields
            gap = len(missing_elems) + len(missing_attrs)
            total = len(xt.elements) + len(xt.attributes)
            if best is None or gap < best[0]:
                best = (gap, total, missing_elems, missing_attrs)
        if best is None:
            continue
        gap, total, missing_elems, missing_attrs = best
        rows.append((spec.name, gap, total, missing_elems, missing_attrs))

    seen: set[str] = set()
    deduped = []
    for r in rows:
        if r[0] in seen:
            continue
        seen.add(r[0])
        deduped.append(r)
    deduped.sort(key=lambda r: r[1], reverse=True)

    print(f"{'spec':<35} {'gap':>4} {'xsd':>4}  missing (elems | attrs)")
    print("-" * 100)
    total_gap = 0
    for name, gap, total, missing_e, missing_a in deduped:
        if gap == 0:
            continue
        total_gap += gap
        elems_str = ", ".join(sorted(missing_e)) if missing_e else "-"
        attrs_str = ", ".join(sorted(missing_a)) if missing_a else "-"
        print(f"{name:<35} {gap:>4} {total:>4}  {elems_str[:60]} | {attrs_str[:30]}")
    print(f"\nTotal gap: {total_gap} missing fields across "
          f"{len([r for r in deduped if r[1] > 0])} specs (root-only)")


# ── Deep report ──────────────────────────────────────────────────────

def _deep_report() -> None:
    from fews_agent.schema import GenericXmlFile

    types_map = _load_all_xsd_types()
    _resolve_extensions(types_map)

    all_gaps: list[DeepGap] = []
    processed: set[str] = set()
    for spec in SPECS:
        if spec.model_class is GenericXmlFile:
            continue
        if spec.model_class.__name__ in processed:
            continue
        processed.add(spec.model_class.__name__)

        xsd_name = _xsd_for_input_key(spec.input_key, spec.output_relpath)
        if not xsd_name:
            continue
        type_candidates = _root_type_candidates(xsd_name)
        if not type_candidates:
            continue

        # Pick the root type whose shallow gap is smallest
        model_fields = _model_field_names(spec.model_class)
        best_root = None
        for rt in type_candidates:
            xt = types_map.get(rt)
            if xt is None:
                continue
            gap = len(set(xt.elements) - model_fields) + len(xt.attributes - model_fields)
            if best_root is None or gap < best_root[0]:
                best_root = (gap, rt)
        if best_root is None:
            continue

        visited: set[tuple[str, str]] = set()
        _audit_deep(spec.model_class, best_root[1], spec.name, types_map, visited, all_gaps)

    # Group by path (which starts with the spec name)
    print(f"{'path':<60} {'gap':>4} missing")
    print("-" * 130)
    total = 0
    for g in sorted(all_gaps, key=lambda g: (-g.total, g.path)):
        total += g.total
        missing = []
        if g.missing_elems:
            missing.append("elems: " + ", ".join(sorted(g.missing_elems)))
        if g.missing_attrs:
            missing.append("attrs: " + ", ".join(sorted(g.missing_attrs)))
        missing_str = " | ".join(missing)
        print(f"{g.path[:58]:<60} {g.total:>4}  {missing_str[:60]}")
    print(f"\nTotal deep gap: {total} missing fields across {len(all_gaps)} nested sites")


def main() -> None:
    if "--deep" in sys.argv:
        _deep_report()
    else:
        _shallow_report()


if __name__ == "__main__":
    main()
