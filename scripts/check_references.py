"""Cross-reference resolution check over a rendered FEWS config tree.

A lightweight, XML-based "semantic-by-parsing" pass (the full typed
semantic validator needs the runner's model triples). It walks every
rendered *.xml, collects declarations and references for the ID kinds that
matter operationally, and reports references that resolve to no declaration
(excluding FEWS $PLACEHOLDER$ / %RUNTIME% values, which FEWS binds at run).

Usage:  python scripts/check_references.py <built-config-dir>

Declarations recognised:
  - parameterId      : <parameter id=...> in any Parameters file
  - locationSetId    : <locationSet id=...> in any LocationSets file
  - locationId       : <location id=...> (Locations.xml), grid <regular/irregular
                       locationId=...> (Grids), and %attr%-templated csvFile ids
                       are treated as declared-by-set (best effort)
  - idMapId          : IdMap*.xml filename stems + <idMap id=...> if present
  - moduleInstanceId : ModuleConfigFiles/*.xml filename stems +
                       <moduleInstanceId> in ModuleInstanceDescriptors

Exit code is always 0 (informational).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from lxml import etree

_PLACEHOLDER = re.compile(r"[$%][A-Za-z0-9_()]+[$%]?")


def _is_placeholder(v: str) -> bool:
    return bool(_PLACEHOLDER.search(v or "")) or not v


def _text_set(tree, tag: str) -> set[str]:
    return {
        (e.text or "").strip()
        for e in tree.iter(f"{{*}}{tag}")
        if (e.text or "").strip()
    }


def analyze(root: Path) -> dict[str, dict[str, set[str]]]:
    """Return {ref_kind: {'resolved': set, 'unresolved': set}} for a built tree.

    Reusable core of the check — the test suite imports this; ``main`` just
    pretty-prints it.
    """
    xmls: list[tuple[Path, object]] = []
    for p in sorted(root.rglob("*.xml")):
        try:
            xmls.append((p, etree.parse(str(p)).getroot()))
        except etree.XMLSyntaxError:
            continue

    declared = {k: set() for k in ("parameter", "locationSet", "location",
                                   "idMap", "moduleInstance")}
    refs = {k: set() for k in ("parameterId", "locationSetId", "locationId",
                               "idMapId", "moduleInstanceId")}
    for path, tree in xmls:
        rel = str(path.relative_to(root)).replace("\\", "/")
        name = path.stem
        for e in tree.iter("{*}parameter"):
            if e.get("id"):
                declared["parameter"].add(e.get("id"))
        for e in tree.iter("{*}locationSet"):
            if e.get("id"):
                declared["locationSet"].add(e.get("id"))
        for e in tree.iter("{*}location"):
            if e.get("id"):
                declared["location"].add(e.get("id"))
        for tag in ("regular", "irregular"):
            for e in tree.iter(f"{{*}}{tag}"):
                if e.get("locationId"):
                    declared["location"].add(e.get("locationId"))
        if "IdMap" in rel:
            declared["idMap"].add(name)
        for e in tree.iter("{*}idMap"):
            if e.get("id"):
                declared["idMap"].add(e.get("id"))
        if rel.startswith("ModuleConfigFiles/"):
            declared["moduleInstance"].add(name)
        for e in tree.iter("{*}moduleInstanceDescriptor"):
            if e.get("id"):
                declared["moduleInstance"].add(e.get("id"))
        for tag, key in (("parameterId", "parameterId"),
                         ("locationSetId", "locationSetId"),
                         ("locationId", "locationId"),
                         ("moduleInstanceId", "moduleInstanceId")):
            for v in _text_set(tree, tag):
                if not _is_placeholder(v):
                    refs[key].add(v)
        for tag in ("idMapId", "importIdMap", "exportIdMap"):
            for v in _text_set(tree, tag):
                if not _is_placeholder(v):
                    refs["idMapId"].add(v)

    out: dict[str, dict[str, set[str]]] = {}
    for ref_key, decl_key in (("parameterId", "parameter"),
                              ("locationSetId", "locationSet"),
                              ("locationId", "location"),
                              ("idMapId", "idMap"),
                              ("moduleInstanceId", "moduleInstance")):
        declset = declared[decl_key] | (
            declared["locationSet"] if ref_key == "locationId" else set()
        )
        unresolved = {r for r in refs[ref_key] if r not in declset}
        out[ref_key] = {"resolved": refs[ref_key] - unresolved,
                        "unresolved": unresolved}
    return out


def main(root: Path) -> None:
    result = analyze(root)
    total = 0
    print(f"\n=== reference check: {root} ===")
    for ref_key, r in result.items():
        n = len(r["resolved"]) + len(r["unresolved"])
        print(f"  {ref_key:16} {len(r['resolved'])}/{n} resolved", end="")
        if r["unresolved"]:
            total += len(r["unresolved"])
            print("  UNRESOLVED: " + ", ".join(sorted(r["unresolved"])))
        else:
            print()
    print(f"  --> {total} unresolved reference(s)\n")



if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
