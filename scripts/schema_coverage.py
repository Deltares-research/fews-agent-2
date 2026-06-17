"""Schema coverage sweep: how complete is each Pydantic model vs its FEWS XSD?

For every entry in the generator registry (``fews_agent.generators.SPECS``)
this:

  1. Reads the spec's Jinja template to recover the root element name and
     the XSD filename (from the ``xsi:schemaLocation`` baked into the
     template).
  2. Walks the XSD from that root element, collecting the set of all
     element + attribute local-names reachable in the content model
     (resolving includes / groups / extensions via the ``xmlschema`` lib).
  3. Walks the Pydantic model recursively, collecting the set of all
     field input-keys (alias-aware), descending into sub-models and
     unwrapping list/optional. Detects "open" subtrees — a free-form
     ``dict[str, Any]`` / ``body`` field can represent any element, so
     those models are flagged as open-by-design rather than incomplete.
  4. Reports, per spec, the names the XSD declares that the model does not
     cover — a ranked worklist for completing the library.

This is a *name-set* coverage signal, deliberately flat: it over-approximates
(a name present under a different parent still counts as covered) but that is
the right bias for a worklist — it never invents a gap, and the names it
surfaces ("logFile", "compressedStateLocation", ...) are real missing fields.

Usage::

    python scripts/schema_coverage.py                 # full table
    python scripts/schema_coverage.py --json out.json  # + machine-readable
    python scripts/schema_coverage.py --spec GeneralAdapterRun  # one model
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo
from rich.console import Console
from rich.table import Table

import xmlschema
from xmlschema.validators import XsdElement, XsdGroup

from fews_agent.generators import SPECS

REPO = Path(__file__).resolve().parents[1]
TEMPLATES = REPO / "fews_agent" / "generators" / "templates"
SCHEMAS = REPO / "schemas"

# Generic XML metadata that is never a model field — don't count as a gap.
_IGNORE_ATTRS = {"version", "xmlns", "schemaLocation", "noNamespaceSchemaLocation"}


# --- template introspection -------------------------------------------------

_SCHEMALOC_RE = re.compile(r'schemaLocation\s*=\s*"([^"]*)"')
_ROOTTAG_RE = re.compile(r"<([A-Za-z][\w.]*)\b")


def template_root_and_xsd(template_name: str) -> tuple[str, str] | None:
    """Return (root_element_localname, xsd_filename) from a template, or None."""
    path = TEMPLATES / template_name
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    m = _SCHEMALOC_RE.search(text)
    if not m:
        return None
    urls = [tok for tok in m.group(1).split() if tok.endswith(".xsd")]
    if not urls:
        return None
    xsd_file = urls[-1].rsplit("/", 1)[-1]
    # The root element is the one that carries xsi:schemaLocation. Find the
    # start tag whose attributes include schemaLocation — robust against
    # leading Jinja macros that emit other XML tags above the real root.
    root_m = re.search(r"<([A-Za-z][\w.]*)\b[^>]*schemaLocation", text)
    if root_m:
        return root_m.group(1), xsd_file
    # Fallback: first real XML start tag (skip the <?xml ...?> declaration).
    for tag in _ROOTTAG_RE.findall(text):
        if tag.lower() == "xml":
            continue
        return tag, xsd_file
    return None


# --- XSD name collection ----------------------------------------------------

def xsd_names(xsd_file: str, root_name: str) -> tuple[set[str], set[str]]:
    """All element + attribute local-names reachable from ``root_name``."""
    schema = xmlschema.XMLSchema(str(SCHEMAS / xsd_file), validation="skip")
    root = schema.elements.get(root_name)
    if root is None:
        # Fall back: some roots are namespaced in the global map.
        for qn, el in schema.elements.items():
            if qn.rsplit("}", 1)[-1] == root_name:
                root = el
                break
    if root is None:
        raise KeyError(f"root element {root_name!r} not found in {xsd_file}")

    elems: set[str] = set()
    attrs: set[str] = set()
    seen_types: set[int] = set()

    def walk_type(t: Any) -> None:
        if t is None or id(t) in seen_types:
            return
        seen_types.add(id(t))
        try:
            for a in getattr(t, "attributes", None) or []:
                if a and not a.startswith("{"):
                    attrs.add(a)
        except Exception:
            pass
        content = getattr(t, "content", None)
        if isinstance(content, XsdGroup):
            walk_group(content)

    def walk_group(g: XsdGroup) -> None:
        for item in g:
            if isinstance(item, XsdElement):
                if item.local_name:
                    elems.add(item.local_name)
                walk_type(item.type)
            elif isinstance(item, XsdGroup):
                walk_group(item)

    walk_type(root.type)
    return elems, attrs


# --- model name collection --------------------------------------------------

def _field_key(name: str, fi: FieldInfo) -> str:
    if fi.alias:
        return fi.alias
    va = fi.validation_alias
    if va:
        return getattr(va, "choices", [va])[0] if hasattr(va, "choices") else str(va)
    return name


def model_names(model_class: type[BaseModel]) -> tuple[set[str], bool]:
    """All field input-keys reachable in the model; plus an "open" flag
    (True if any reachable field is a free-form dict that can hold
    arbitrary elements)."""
    names: set[str] = set()
    open_flag = False
    seen: set[type] = set()

    def unwrap(annot: Any) -> list[type]:
        """Return BaseModel classes referenced by an annotation, and set
        open_flag for free-form dicts."""
        nonlocal open_flag
        origin = get_origin(annot)
        args = get_args(annot)
        if isinstance(annot, type) and issubclass(annot, BaseModel):
            return [annot]
        if origin is dict:
            val = args[1] if len(args) >= 2 else Any
            if val is Any:
                open_flag = True
            else:
                return unwrap(val)
            return []
        if annot is dict or annot is Any:
            open_flag = True
            return []
        out: list[type] = []
        for a in args:
            if a is type(None):
                continue
            out.extend(unwrap(a))
        return out

    def walk(mc: type[BaseModel]) -> None:
        if mc in seen:
            return
        seen.add(mc)
        for fname, fi in mc.model_fields.items():
            names.add(_field_key(fname, fi))
            for sub in unwrap(fi.annotation):
                walk(sub)

    walk(model_class)
    return names, open_flag


# --- per-spec analysis ------------------------------------------------------

def analyse(model_class: type[BaseModel], template_name: str) -> dict | None:
    rx = template_root_and_xsd(template_name)
    if rx is None:
        return None
    root, xsd_file = rx
    if not (SCHEMAS / xsd_file).is_file():
        return {"model": model_class.__name__, "xsd": xsd_file, "skipped": "xsd missing"}
    try:
        x_elems, x_attrs = xsd_names(xsd_file, root)
    except Exception as exc:  # noqa: BLE001
        return {"model": model_class.__name__, "xsd": xsd_file, "skipped": f"xsd error: {exc}"}
    m_names, open_flag = model_names(model_class)

    xsd_all = (x_elems | x_attrs) - _IGNORE_ATTRS
    missing = sorted(xsd_all - m_names)
    covered = len(xsd_all) - len(missing)
    coverage = (covered / len(xsd_all)) if xsd_all else 1.0
    return {
        "model": model_class.__name__,
        "xsd": xsd_file,
        "root": root,
        "xsd_names": len(xsd_all),
        "covered": covered,
        "missing_count": len(missing),
        "coverage": round(coverage, 3),
        "open": open_flag,
        "missing": missing,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--json", type=Path, help="Write full JSON report here")
    p.add_argument("--spec", help="Only analyse this model class name")
    p.add_argument("--min-missing", type=int, default=1,
                   help="Only show rows with >= this many missing names (default 1)")
    args = p.parse_args(argv)
    console = Console()

    seen: set[tuple[str, str]] = set()
    rows: list[dict] = []
    skipped: list[dict] = []
    for spec in SPECS:
        if args.spec and spec.model_class.__name__ != args.spec:
            continue
        key = (spec.model_class.__name__, spec.template_name)
        if key in seen:
            continue
        seen.add(key)
        r = analyse(spec.model_class, spec.template_name)
        if r is None:
            continue
        if r.get("skipped"):
            skipped.append(r)
        else:
            rows.append(r)

    # Open-by-design models can represent anything — separate them out.
    open_rows = [r for r in rows if r["open"]]
    closed = [r for r in rows if not r["open"]]
    incomplete = sorted(
        [r for r in closed if r["missing_count"] >= args.min_missing],
        key=lambda r: (-r["missing_count"], r["model"]),
    )
    complete = [r for r in closed if r["missing_count"] == 0]

    table = Table(title="Schema coverage — incomplete models (worst first)")
    table.add_column("model")
    table.add_column("xsd")
    table.add_column("xsd names", justify="right")
    table.add_column("missing", justify="right")
    table.add_column("cov%", justify="right")
    table.add_column("sample missing names")
    for r in incomplete:
        table.add_row(
            r["model"], r["xsd"], str(r["xsd_names"]),
            str(r["missing_count"]), f"{r['coverage']*100:.0f}",
            ", ".join(r["missing"][:8]) + (" …" if r["missing_count"] > 8 else ""),
        )
    console.print(table)

    console.print(
        f"\n[bold]Totals[/bold]  analysed={len(rows)}  "
        f"[green]complete={len(complete)}[/green]  "
        f"[yellow]incomplete={len(incomplete)}[/yellow]  "
        f"[cyan]open-by-design={len(open_rows)}[/cyan]  "
        f"[dim]skipped={len(skipped)}[/dim]"
    )
    if incomplete:
        total_missing = sum(r["missing_count"] for r in incomplete)
        console.print(f"[dim]total missing names across incomplete models: {total_missing}[/dim]")

        # Highest-leverage fixes: a name missing from many models usually
        # lives in a shared type — fix it once, clear it everywhere.
        import collections
        freq = collections.Counter()
        for r in incomplete:
            for n in r["missing"]:
                freq[n] += 1
        shared = [(n, c) for n, c in freq.most_common() if c >= 2]
        if shared:
            ft = Table(title="Recurring missing names (likely shared types — fix once, clear many)")
            ft.add_column("missing name")
            ft.add_column("# models", justify="right")
            for n, c in shared[:20]:
                ft.add_row(n, str(c))
            console.print(ft)

    if args.json:
        args.json.write_text(json.dumps(
            {"incomplete": incomplete, "complete": [r["model"] for r in complete],
             "open": [r["model"] for r in open_rows], "skipped": skipped},
            indent=2,
        ), encoding="utf-8")
        console.print(f"Wrote JSON report: [bold]{args.json}[/bold]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
