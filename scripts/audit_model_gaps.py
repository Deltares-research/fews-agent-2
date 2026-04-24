"""Audit typed Pydantic models against their FEWS XSDs.

For each SPECS entry that resolves to a single XSD (non-GenericXmlFile),
find the XSD root complex type and compare its child element and
attribute names against the Pydantic model's fields. Report discrepancies
sorted by gap size.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from lxml import etree

from fews_agent.generators import SPECS


XS_NS = {"xs": "http://www.w3.org/2001/XMLSchema"}
SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas"


def _collect_xsd_fields(xsd_name: str, root_element_name: str) -> tuple[set[str], set[str]]:
    """Return (child element names, attribute names) in the root
    complex type of `xsd_name`. Follows type references one level deep.
    """
    path = SCHEMAS_DIR / xsd_name
    if not path.exists():
        return set(), set()
    tree = etree.parse(str(path))
    root = tree.getroot()

    # Locate the root element declaration to find its type
    root_type = None
    for el in root.findall("xs:element", XS_NS):
        if el.get("name") == root_element_name:
            root_type = el.get("type", "").split(":")[-1]
            break
    if not root_type:
        return set(), set()

    target_ct = None
    for ct in root.findall("xs:complexType", XS_NS):
        if ct.get("name") == root_type:
            target_ct = ct
            break
    if target_ct is None:
        return set(), set()

    # Only consider direct children of the top-level <sequence>/<choice>
    # plus direct <attribute> children of the complex type itself. Nested
    # anonymous complexTypes inside elements aren't part of the root's
    # field surface.
    import re
    ns_re = re.compile(r"\}(\w+)")

    def _localname(el) -> str:
        m = ns_re.search(str(el.tag))
        return m.group(1) if m else ""

    elements: set[str] = set()

    def _walk(container):
        # container is a <sequence> or <choice> etc. We collect direct
        # <element> children. Nested <sequence>/<choice>/<group> descend.
        for child in container:
            lname = _localname(child)
            if lname == "element" and child.get("name"):
                elements.add(child.get("name"))
            elif lname in ("sequence", "choice"):
                _walk(child)
            # group refs / any: ignored (external)

    # Start with the complexType's direct sequence/choice child(ren)
    for container in target_ct:
        lname = _localname(container)
        if lname in ("sequence", "choice"):
            _walk(container)
        elif lname == "complexContent":
            # extension-based types: walk the extension
            for sub in container:
                if _localname(sub) == "extension":
                    for e2 in sub:
                        if _localname(e2) in ("sequence", "choice"):
                            _walk(e2)

    attributes: set[str] = set()
    for child in target_ct:
        if _localname(child) == "attribute" and child.get("name"):
            attributes.add(child.get("name"))
    return elements, attributes


def _model_fields(model_class: type) -> set[str]:
    names: set[str] = set()
    for field_name, info in model_class.model_fields.items():
        # Include both the field name and any alias
        names.add(field_name)
        # Strip trailing underscore for python-keyword fields (int_ -> int)
        if field_name.endswith("_"):
            names.add(field_name.rstrip("_"))
        if info.alias:
            names.add(info.alias)
    return names


def _xsd_for_input_key(input_key: str, output_relpath: Path) -> str | None:
    """Heuristic: XSD filename is input_key-ish. Try a few variants."""
    candidates = [
        f"{input_key}.xsd",
        f"{input_key[0].lower() + input_key[1:]}.xsd",
        f"{output_relpath.stem[0].lower() + output_relpath.stem[1:]}.xsd",
    ]
    for c in candidates:
        if (SCHEMAS_DIR / c).exists():
            return c
    return None


def _root_element_candidates(xsd_name: str) -> list[str]:
    """All top-level element names in the XSD — useful when a schema
    exports more than one root (e.g. parameters.xsd has both
    ``parameters`` and ``parameterGroups``)."""
    path = SCHEMAS_DIR / xsd_name
    if not path.exists():
        return []
    tree = etree.parse(str(path))
    out: list[str] = []
    for el in tree.getroot().findall("xs:element", XS_NS):
        name = el.get("name")
        if name:
            out.append(name)
    return out


def main() -> None:
    # Skip GenericXmlFile entries — they're intentionally passthrough.
    from fews_agent.schema import GenericXmlFile

    rows: list[tuple[str, int, int, set[str], set[str]]] = []
    for spec in SPECS:
        if spec.model_class is GenericXmlFile:
            continue
        xsd_name = _xsd_for_input_key(spec.input_key, spec.output_relpath)
        if not xsd_name:
            continue
        root_candidates = _root_element_candidates(xsd_name)
        if not root_candidates:
            continue
        model_fields = _model_fields(spec.model_class)
        # Pick the root whose element set has the fewest missing fields —
        # handles XSDs that expose multiple roots (e.g. parameters.xsd
        # with parameters AND parameterGroups elements).
        best = None
        for root_name in root_candidates:
            xsd_elems, xsd_attrs = _collect_xsd_fields(xsd_name, root_name)
            missing_elems = xsd_elems - model_fields
            missing_attrs = xsd_attrs - model_fields
            gap = len(missing_elems) + len(missing_attrs)
            total = len(xsd_elems) + len(xsd_attrs)
            if best is None or gap < best[0]:
                best = (gap, total, missing_elems, missing_attrs)
        if best is None:
            continue
        gap, total, missing_elems, missing_attrs = best
        rows.append((spec.name, gap, total, missing_elems, missing_attrs))

    # Deduplicate: many SPECS share a model. Keep one row per model.
    seen_models: set[str] = set()
    deduped: list[tuple[str, int, int, set[str], set[str]]] = []
    for r in rows:
        # Use spec name prefix as a rough model-key proxy
        if r[0] in seen_models:
            continue
        seen_models.add(r[0])
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
    print(f"\nTotal gap: {total_gap} missing fields across {len([r for r in deduped if r[1] > 0])} specs")


if __name__ == "__main__":
    main()
