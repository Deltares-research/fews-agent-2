"""Mine the tutorial config for cross-file patterns.

Walks ``examples/config-tutorial/`` and clusters its 119 files into
candidate "patterns" — multi-file features that recur in real
projects. A pattern is a coherent set of files that together implement
one capability (an HRDPS importer, a Liard model run, ...) and whose
inputs vary per project.

The miner uses three signals:

  1. **Filename stem clustering** — files in
     ``ModuleConfigFiles/Import/<family>/Import<NAME>.xml`` belong to
     the ``<NAME>`` import pattern. Companion ``Retrieve<NAME>.xml`` /
     ``Preprocess<NAME>.xml`` siblings join the same cluster.
  2. **Cross-file references** — workflow files in
     ``WorkflowFiles/Import/<family>/Import<NAME>Grids.xml`` link back
     to the Import config; idMap files in
     ``IdMapFiles/<family>/IdImport<NAME>.xml`` link too.
  3. **Module-instance declarations** —
     ``ModuleInstanceDescriptors.xml`` entries with id matching
     ``Import<NAME>`` / ``Retrieve<NAME>`` etc. attach to that cluster.

Output: ``data/patterns/mining_report.json`` listing each pattern with
its files, its detected variables (location IDs, parameters,
schedules), and a confidence note. Hand-review then refines.

This is a one-shot exploratory tool — not a runtime component. Used
to bootstrap the pattern library, then patterns get hand-edited.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, asdict, field
from pathlib import Path

from lxml import etree

REPO_ROOT = Path(__file__).resolve().parents[1]
TUTORIAL = REPO_ROOT / "examples" / "config-tutorial"
OUTPUT = REPO_ROOT / "data" / "patterns" / "mining_report.json"


# ---------------------------------------------------------------------------
# Pattern record
# ---------------------------------------------------------------------------

@dataclass
class PatternCandidate:
    """One mined pattern — set of files that implement one feature."""

    name: str
    kind: str  # "import" | "model_basin" | "preprocess" | "singleton" | "other"
    files: list[str] = field(default_factory=list)  # tutorial-relative paths
    referenced_location_ids: set[str] = field(default_factory=set)
    referenced_parameter_ids: set[str] = field(default_factory=set)
    module_instance_ids: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "files": sorted(self.files),
            "referenced_location_ids": sorted(self.referenced_location_ids),
            "referenced_parameter_ids": sorted(self.referenced_parameter_ids),
            "module_instance_ids": sorted(self.module_instance_ids),
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Mining
# ---------------------------------------------------------------------------

# Filename → pattern-name regexes. The captured group is the pattern key.
_IMPORT_RX = re.compile(
    r"^ModuleConfigFiles/Import/[^/]+/(?:Import|Retrieve|Preprocess)([A-Z][A-Za-z0-9]+)\.xml$"
)
_WORKFLOW_IMPORT_RX = re.compile(
    r"^WorkflowFiles/Import/[^/]+/(?:Import|Retrieve|Preprocess)([A-Z][A-Za-z0-9]+?)(?:Grids)?\.xml$"
)
_IDMAP_IMPORT_RX = re.compile(
    r"^IdMapFiles/[^/]+/(?:IdImport|IdExport)([A-Z][A-Za-z0-9]+)\.xml$"
)
_MODELRUN_RX = re.compile(
    r"^ModuleConfigFiles/ModelRun/([^/]+)/.+\.xml$"
)
_MODELRUN_WF_RX = re.compile(
    r"^WorkflowFiles/ModelRun/([^/]+)/.+\.xml$"
)
_PREPROCESS_BASIN_RX = re.compile(
    r"^WorkflowFiles/Preprocess/([^/]+)/.+\.xml$"
)
_COLDSTATE_RX = re.compile(
    r"^ColdStateFiles/(.+)/.+$"
)


def mine() -> dict:
    """Walk the tutorial, build PatternCandidate list."""
    files = sorted(_walk(TUTORIAL))
    rels = [str(p.relative_to(TUTORIAL)).replace("\\", "/") for p in files]

    patterns: dict[str, PatternCandidate] = {}
    singletons: list[str] = []

    for rel in rels:
        m = _IMPORT_RX.match(rel)
        if m:
            key = m.group(1)
            p = patterns.setdefault(
                f"import_{key}",
                PatternCandidate(name=f"import_{key}", kind="import"),
            )
            p.files.append(rel)
            continue

        m = _WORKFLOW_IMPORT_RX.match(rel)
        if m:
            key = m.group(1)
            p = patterns.setdefault(
                f"import_{key}",
                PatternCandidate(name=f"import_{key}", kind="import"),
            )
            p.files.append(rel)
            continue

        m = _IDMAP_IMPORT_RX.match(rel)
        if m:
            key = m.group(1)
            p = patterns.setdefault(
                f"import_{key}",
                PatternCandidate(name=f"import_{key}", kind="import"),
            )
            p.files.append(rel)
            continue

        m = _MODELRUN_RX.match(rel) or _MODELRUN_WF_RX.match(rel)
        if m:
            key = m.group(1)
            p = patterns.setdefault(
                f"model_basin_{key}",
                PatternCandidate(
                    name=f"model_basin_{key}", kind="model_basin",
                ),
            )
            p.files.append(rel)
            continue

        m = _PREPROCESS_BASIN_RX.match(rel)
        if m:
            key = m.group(1)
            # Attach preprocess to the basin pattern so they cluster.
            p = patterns.setdefault(
                f"model_basin_{key}",
                PatternCandidate(
                    name=f"model_basin_{key}", kind="model_basin",
                ),
            )
            p.files.append(rel)
            continue

        m = _COLDSTATE_RX.match(rel)
        if m:
            # Cold-state files live alongside their basin pattern.
            key = m.group(1).split("/")[0]
            # Strip the trailing " Default" / " Historic" / etc.
            basin_token = key.split(" ", 1)[0]
            p = patterns.setdefault(
                f"coldstate_{basin_token}",
                PatternCandidate(
                    name=f"coldstate_{basin_token}", kind="other",
                ),
            )
            p.files.append(rel)
            continue

        singletons.append(rel)

    # Singleton pattern catches everything else — this is mostly the
    # one-per-project files (Region/System/Display configs).
    patterns["singletons"] = PatternCandidate(
        name="singletons", kind="singleton",
    )
    patterns["singletons"].files = sorted(singletons)
    patterns["singletons"].notes.append(
        f"{len(singletons)} files; one-per-project (Region/System/Display "
        "configs, ModuleInstanceDescriptors aggregator, etc.)"
    )

    # Pull module-instance ids out of ModuleInstanceDescriptors.xml.
    mid_path = TUTORIAL / "RegionConfigFiles" / "ModuleInstanceDescriptors.xml"
    if mid_path.is_file():
        ids = _extract_module_instance_ids(mid_path)
        for pat in patterns.values():
            if pat.kind in {"import", "model_basin"}:
                key = pat.name.split("_", 1)[1]
                for mid in ids:
                    if key in mid:
                        pat.module_instance_ids.add(mid)

    # Heuristic: import patterns reference location/parameter ids.
    for pat in patterns.values():
        if pat.kind == "import":
            for f in pat.files:
                p = TUTORIAL / f
                if p.is_file():
                    locs, params = _extract_id_refs(p)
                    pat.referenced_location_ids.update(locs)
                    pat.referenced_parameter_ids.update(params)

    return {
        "tutorial_files": len(rels),
        "pattern_count": len([p for p in patterns.values() if p.name != "singletons"]),
        "patterns": [p.to_json() for p in sorted(patterns.values(), key=lambda x: (x.kind, x.name))],
    }


def _walk(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.xml") if p.is_file()]


def _extract_module_instance_ids(path: Path) -> list[str]:
    """Pull ``<id>...</id>`` values from ModuleInstanceDescriptors.xml."""
    try:
        tree = etree.parse(str(path))
    except Exception:
        return []
    ns = {"f": "http://www.wldelft.nl/fews"}
    return [el.text for el in tree.findall(".//f:moduleInstanceDescriptor", ns) if el.get("id")] + \
           [el.get("id") for el in tree.findall(".//f:moduleInstanceDescriptor", ns) if el.get("id")]


def _extract_id_refs(path: Path) -> tuple[set[str], set[str]]:
    """Pull locationId / parameterId text values out of any FEWS file."""
    locs: set[str] = set()
    params: set[str] = set()
    try:
        tree = etree.parse(str(path))
    except Exception:
        return locs, params
    ns = {"f": "http://www.wldelft.nl/fews"}
    for el in tree.findall(".//f:locationId", ns):
        if el.text:
            locs.add(el.text.strip())
    for el in tree.findall(".//f:parameterId", ns):
        if el.text:
            params.add(el.text.strip())
    return locs, params


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    report = mine()
    OUTPUT.write_text(json.dumps(report, indent=2, default=list), encoding="utf-8")
    print(f"wrote {OUTPUT}")
    print(f"  tutorial_files={report['tutorial_files']}")
    print(f"  patterns={report['pattern_count']}")
    print()
    for pat in report["patterns"]:
        marker = "*" if pat["name"] == "singletons" else " "
        print(
            f"  {marker} [{pat['kind']:14}] {pat['name']:30} "
            f"{len(pat['files']):3} file(s)"
        )
