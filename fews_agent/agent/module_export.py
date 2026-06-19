"""Module + dependency export — the closure walker.

`done` + a full build produces a whole FEWS config (~30+ files). But a
configurator who only wants *one module* — to drop into an existing
config, or as a minimal standalone — needs the module plus exactly the
files that declare what it references, and nothing else.

This module computes that set. Starting from a module's rendered files
(the *seeds*), it follows **outgoing** id references — `parameterId`,
`locationId`, `idMapId`, `unitConversionsId`, ... — and pulls in the
files that *declare* those ids, transitively. It stops at the project-
chrome boundary: files that reference *into* the module (Topology,
Filters, DisplayGroups, descriptors, ...) are dependents, not
dependencies, and are excluded.

The result has three parts:

- **needed** — the module + the dependency files it pulled in. A
  self-contained subset that XSD-validates and whose references resolve.
- **external** — references no dependency file satisfied (a sibling
  module's instance, or an id only declared in chrome). These become a
  manifest: "your target config must already declare these."
- **chrome** — everything excluded.

The walker is deterministic and does no I/O: it takes a ``{relpath:
content}`` map (so it's trivially testable) and returns relpaths. The
caller renders the project, runs this, and copies the ``needed`` files.

Reuses the same idea as ``validation/semantic.py`` (declared vs
referenced ids) but at file granularity and following edges in one
direction only.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Iterable

_PLACEHOLDER = re.compile(r"\$[A-Z0-9_]+\$")
_NS = re.compile(r"\{[^}]+\}")


def _tag(el: ET.Element) -> str:
    return _NS.sub("", el.tag)


def _is_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER.search(value or ""))


# Element tags whose TEXT content is a referenced id → the id's type key.
# (The type key is just a namespace for the value; it groups declarations
# and references of the same kind.)
_REF_TAGS: dict[str, str] = {
    "parameterId": "parameter",
    "locationId": "location",
    "locationSetId": "locationSet",
    "moduleInstanceId": "moduleInstance",
    "idMapId": "idMap",
    "unitConversionsId": "unitConversions",
    "workflowId": "workflow",
    "qualifierId": "qualifier",
}

# RegionConfig files that declare ids and are genuine *dependencies*
# (a module can't resolve without them). Matched on basename.
_DEPENDENCY_BASENAMES: frozenset[str] = frozenset({
    "Parameters.xml", "Grids.xml", "TimeSteps.xml", "Locations.xml",
    "LocationSets.xml", "Qualifiers.xml",
})
# Whole directories whose files are filename-declared dependencies.
_DEPENDENCY_DIRS: tuple[str, ...] = ("IdMapFiles/", "UnitConversionsFiles/")


def classify(relpath: str) -> str:
    """Bucket a rendered file: dependency / descriptor / module / chrome."""
    rel = relpath.replace("\\", "/")
    base = rel.rsplit("/", 1)[-1]
    if base in _DEPENDENCY_BASENAMES:
        return "dependency"
    if rel.startswith(_DEPENDENCY_DIRS):
        return "dependency"
    if base.endswith("Descriptors.xml"):
        # A module instance is declared by its config filename, so the
        # descriptor is not required for a single-module bundle. Treated
        # as chrome (excluded) but named distinctly for clarity.
        return "descriptor"
    if rel.startswith(("ModuleConfigFiles/", "WorkflowFiles/")):
        return "module"
    return "chrome"


@dataclass(frozen=True)
class ExternalRef:
    """A reference the closure could not satisfy from a dependency file."""

    id_type: str
    value: str
    reason: str  # "undeclared" | "only in chrome: <files>"

    def __str__(self) -> str:
        return f"{self.id_type}:{self.value} ({self.reason})"


@dataclass
class ExportResult:
    seeds: list[str] = field(default_factory=list)
    needed: list[str] = field(default_factory=list)
    chrome: list[str] = field(default_factory=list)
    external: list[ExternalRef] = field(default_factory=list)
    # needed-file relpath → the (id_type, value) refs that pulled it in.
    pulled_by: dict[str, list[tuple[str, str]]] = field(default_factory=dict)


def _index(files: dict[str, str]):
    """Return (declared, refs): declared[idtype][value]=[relpaths],
    refs[relpath]={(idtype, value)}."""
    declared: dict[str, dict[str, list[str]]] = {}
    refs: dict[str, set[tuple[str, str]]] = {}

    def declare(idtype: str, value: str, rel: str) -> None:
        declared.setdefault(idtype, {}).setdefault(value, []).append(rel)

    for rel, content in files.items():
        r = rel.replace("\\", "/")
        stem = r.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        # Filename-based declarations.
        if r.startswith("IdMapFiles/"):
            declare("idMap", stem, rel)
        if r.startswith("UnitConversionsFiles/"):
            declare("unitConversions", stem, rel)
        if r.startswith("ModuleConfigFiles/"):
            declare("moduleInstance", stem, rel)
        if r.startswith("WorkflowFiles/"):
            declare("workflow", stem, rel)
        try:
            root = ET.fromstring(content.encode("utf-8"))
        except ET.ParseError:
            refs[rel] = set()
            continue
        # Element-based declarations + references.
        found: set[tuple[str, str]] = set()
        for el in root.iter():
            t = _tag(el)
            eid = el.get("id")
            if r.endswith("Parameters.xml") and t == "parameter" and eid:
                declare("parameter", eid, rel)
            elif r.endswith("Locations.xml") and t == "location" and eid:
                declare("location", eid, rel)
            elif r.endswith("LocationSets.xml") and t == "locationSet" and eid:
                declare("locationSet", eid, rel)
            elif r.endswith("TimeSteps.xml") and t == "timeStep" and eid:
                declare("timeStep", eid, rel)
            elif r.endswith("Qualifiers.xml") and t == "qualifier" and eid:
                declare("qualifier", eid, rel)
            if r.endswith("Grids.xml"):
                gloc = el.get("locationId")
                if gloc and not _is_placeholder(gloc):
                    declare("location", gloc, rel)
            if t == "moduleInstanceDescriptor" and eid:
                declare("moduleInstance", eid, rel)
            if t == "workflowDescriptor" and eid:
                declare("workflow", eid, rel)
            # References (text content of ref tags).
            if t in _REF_TAGS and el.text:
                val = el.text.strip()
                if val and not _is_placeholder(val):
                    found.add((_REF_TAGS[t], val))
        refs[rel] = found

    return declared, refs


def compute_closure(
    files: dict[str, str], seeds: Iterable[str],
) -> ExportResult:
    """Follow outgoing id references from ``seeds`` to a dependency closure.

    Args:
        files: ``{relpath: xml_content}`` for the whole rendered project.
        seeds: relpaths of the module's own files (the export target).

    Returns:
        ExportResult with needed / chrome / external / pulled_by.
    """
    declared, refs = _index(files)
    seeds = [s for s in seeds if s in files]
    needed: set[str] = set(seeds)
    pulled_by: dict[str, list[tuple[str, str]]] = {}
    external: list[ExternalRef] = []
    seen_external: set[tuple[str, str]] = set()

    frontier = list(seeds)
    while frontier:
        new: list[str] = []
        for f in frontier:
            for ref in sorted(refs.get(f, ())):
                idtype, value = ref
                decls = declared.get(idtype, {}).get(value, [])
                # Already satisfied by a file in the bundle (e.g. a
                # module's own moduleInstanceId, or an already-pulled dep).
                if any(d in needed for d in decls):
                    continue
                # Prefer a real dependency declarer (skip descriptor/chrome).
                picked = next(
                    (d for d in decls if classify(d) == "dependency"), None,
                )
                if picked is not None:
                    if picked not in needed:
                        needed.add(picked)
                        new.append(picked)
                    pulled_by.setdefault(picked, [])
                    if ref not in pulled_by[picked]:
                        pulled_by[picked].append(ref)
                elif ref not in seen_external:
                    seen_external.add(ref)
                    if decls:
                        reason = "only in chrome: " + ", ".join(sorted(decls))
                    else:
                        reason = "undeclared"
                    external.append(ExternalRef(idtype, value, reason))
        frontier = new

    chrome = sorted(f for f in files if f not in needed)
    return ExportResult(
        seeds=sorted(seeds),
        needed=sorted(needed),
        chrome=chrome,
        external=sorted(external, key=lambda e: (e.id_type, e.value)),
        pulled_by={k: sorted(v) for k, v in pulled_by.items()},
    )


# Dependency files that the full build emits whole but that may carry
# entries beyond what the module references. ``trim_dependency_files``
# drops the unreferenced entries (the build runner already trims idMaps
# and grids on the full-project path).
_TRIMMABLE_BASENAMES: frozenset[str] = frozenset({
    "Parameters.xml", "Grids.xml", "LocationSets.xml", "TimeSteps.xml",
})

# Namespaces every FEWS file carries; re-declared on re-serialization so a
# trimmed file round-trips without ElementTree's ``ns0:`` prefixing.
_FEWS_NS = "http://www.wldelft.nl/fews"
_XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"


def _entry_refs(el: ET.Element) -> set[tuple[str, str]]:
    """Outgoing id references contained anywhere under ``el``.

    Lets a kept entry pull in the entries *it* references — e.g. a
    ``locationSet`` whose body names another ``locationSetId``.
    """
    out: set[tuple[str, str]] = set()
    for sub in el.iter():
        t = _tag(sub)
        if t in _REF_TAGS and sub.text:
            v = sub.text.strip()
            if v and not _is_placeholder(v):
                out.add((_REF_TAGS[t], v))
    return out


def _declared_entries(root: ET.Element, basename: str):
    """Yield ``(idtype, id, element, parent)`` for each trimmable top-level
    declaration in a parsed dependency file.

    A trimmable entry is one the closure can decide to keep or drop on its
    own: a ``<parameter>`` (nested one level under its group), a grid
    ``<regular>``/``<irregular>``/... entry keyed by ``@locationId``, a
    ``<locationSet>``, or a ``<timeStep>``.
    """
    if basename == "Parameters.xml":
        for grp in list(root):
            if _tag(grp) != "parameterGroup":
                continue
            for child in list(grp):
                if _tag(child) == "parameter" and child.get("id"):
                    yield ("parameter", child.get("id"), child, grp)
    elif basename == "Grids.xml":
        for child in list(root):
            loc = child.get("locationId")
            if loc:
                yield ("location", loc, child, root)
    elif basename == "LocationSets.xml":
        for child in list(root):
            if _tag(child) == "locationSet" and child.get("id"):
                yield ("locationSet", child.get("id"), child, root)
    elif basename == "TimeSteps.xml":
        for child in list(root):
            if _tag(child) == "timeStep" and child.get("id"):
                yield ("timeStep", child.get("id"), child, root)


def _serialize(root: ET.Element) -> str:
    """Re-serialize a trimmed root with the FEWS default namespace intact."""
    ET.register_namespace("", _FEWS_NS)
    ET.register_namespace("xsi", _XSI_NS)
    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"


def trim_dependency_files(
    files: dict[str, str], result: ExportResult,
) -> dict[str, str]:
    """Trim each trimmable dependency file to the entries the module needs.

    Starting from the references carried by the **non-trimmable** needed
    files (the module + idMap + unitConversions), this keeps only the
    declared entries those references reach — transitively, so a kept
    ``locationSet`` pulls in the sets it names. Unreferenced ``parameter``
    / grid / ``locationSet`` / ``timeStep`` entries are removed, and a
    ``parameterGroup`` left empty is dropped with them.

    Returns ``{relpath: trimmed_xml}`` for the files that were actually
    trimmed; a file is omitted (the caller keeps the original) when there
    is nothing to drop or when trimming would remove *every* entry — the
    same empty-result safeguard the build runner uses.
    """
    trimmable = [
        f for f in result.needed
        if f.rsplit("/", 1)[-1] in _TRIMMABLE_BASENAMES and f in files
    ]
    if not trimmable:
        return {}
    trimmable_set = set(trimmable)
    _declared, refs = _index(files)

    # Seed the entry-closure with refs from every non-trimmable needed file.
    # A trimmable file's own refs only matter once its carrying entry is kept.
    frontier: list[tuple[str, str]] = []
    for f in result.needed:
        if f not in trimmable_set:
            frontier.extend(refs.get(f, ()))

    # Index every trimmable entry by (idtype, id) → its outgoing refs.
    parsed: dict[str, ET.Element] = {}
    entry_refs: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for f in trimmable:
        base = f.rsplit("/", 1)[-1]
        try:
            root = ET.fromstring(files[f].encode("utf-8"))
        except ET.ParseError:
            continue
        parsed[f] = root
        for idtype, eid, el, _parent in _declared_entries(root, base):
            entry_refs.setdefault((idtype, eid), set()).update(_entry_refs(el))

    # BFS: keep entries reachable from the seed refs, following each kept
    # entry's own outgoing refs.
    kept: set[tuple[str, str]] = set()
    seen: set[tuple[str, str]] = set(frontier)
    queue = list(frontier)
    while queue:
        ref = queue.pop()
        if ref in entry_refs and ref not in kept:
            kept.add(ref)
            for nxt in entry_refs[ref]:
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)

    trimmed: dict[str, str] = {}
    for f, root in parsed.items():
        base = f.rsplit("/", 1)[-1]
        entries = list(_declared_entries(root, base))
        drop = [
            (el, parent) for (idtype, eid, el, parent) in entries
            if (idtype, eid) not in kept
        ]
        if not drop or len(drop) == len(entries):
            continue  # nothing to trim, or would empty the file → keep whole
        for el, parent in drop:
            parent.remove(el)
        if base == "Parameters.xml":
            for grp in list(root):
                if _tag(grp) == "parameterGroup" and not any(
                    _tag(c) == "parameter" for c in grp
                ):
                    root.remove(grp)
        trimmed[f] = _serialize(root)
    return trimmed


def render_manifest(
    result: ExportResult, module_name: str,
    trimmed: set[str] | None = None,
) -> str:
    """Human-readable MANIFEST.md for an exported module bundle."""
    lines = [
        f"# Export: module `{module_name}`",
        "",
        "Self-contained subset: this module plus the files that declare "
        "what it references. Project chrome (Topology, Filters, display, "
        "permissions, descriptors, ...) is excluded.",
        "",
        f"## Module files ({len(result.seeds)})",
    ]
    lines += [f"- `{s}`" for s in result.seeds]

    deps = [f for f in result.needed if f not in result.seeds]
    lines += ["", f"## Dependencies pulled in ({len(deps)})"]
    if not deps:
        lines.append("- (none)")
    trimmed = trimmed or set()
    for f in deps:
        why = ", ".join(f"{t}:{v}" for t, v in result.pulled_by.get(f, []))
        note = ""
        if f in trimmed:
            note = "  _(trimmed to the referenced entries above)_"
        elif f.rsplit("/", 1)[-1] in _TRIMMABLE_BASENAMES:
            note = "  _(emitted whole; every entry is referenced)_"
        lines.append(f"- `{f}` — satisfies {why}{note}")

    lines += ["", f"## External dependencies — your target config must "
              f"declare these ({len(result.external)})"]
    if not result.external:
        lines.append("- (none — the bundle is self-contained)")
    for ext in result.external:
        lines.append(f"- `{ext.id_type}:{ext.value}` ({ext.reason})")

    lines += ["", f"## Excluded as project chrome ({len(result.chrome)})",
              "- " + ", ".join(f.rsplit("/", 1)[-1] for f in result.chrome)]
    return "\n".join(lines) + "\n"


__all__ = [
    "ExportResult", "ExternalRef", "classify",
    "compute_closure", "render_manifest", "trim_dependency_files",
]
