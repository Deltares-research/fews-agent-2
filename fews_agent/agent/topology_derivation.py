"""Derive Topology.xml from rendered workflow files.

Phase (a) deterministic deriver. Topology is the UI navigation tree:
each leaf points at a workflow, and groups bundle related workflows
under a parent node. The tree's *shape* follows a strict convention:

  Information Sources         (static — wiki + data-source links)
  Import <category> Grids/Stations  (one group per Import* workflow family)
  Run <model>                 (one group per basin/model with Historic + per-NWP forecasts)

Filenames already encode the category and model: ``ImportHRDPSGrids``,
``RunLiardGDPSForecast``. The deriver groups workflows by the prefix
captured from the filename and emits a topology that matches the
project's actual scope. Configurator can override entirely by providing
their own ``topology.yaml`` in ``inputs/``.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .blueprint import RenderedFile


_PLACEHOLDER_RE = re.compile(r"\$[A-Z0-9_]+\$")


def _is_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(value or ""))


# Static subtree: external information sources. Universal across
# projects — same wiki and operational data links for every Delft-FEWS
# operator.
_INFORMATION_SOURCES = {
    "id": "Information_Sources",
    "name": "Information Sources",
    "nodes": [
        {
            "id": "Delft-FEWS",
            "node": [
                {
                    "id": "Delft-FEWS_Wiki",
                    "name": "Delft-FEWS Documentation",
                    "url": "https://publicwiki.deltares.nl/display/FEWSDOC/Home",
                    "localRun": False,
                    "showRunApprovedForecastButton": False,
                },
                {
                    "id": "Delft-FEWS_UserGuide",
                    "name": "Delft-FEWS User Guide",
                    "url": "https://publicwiki.deltares.nl/display/FEWSDOC/Using+Delft-FEWS+-+User+Guide",
                    "localRun": False,
                    "showRunApprovedForecastButton": False,
                },
                {
                    "id": "Delft_FEWS",
                    "name": "Delft-FEWS Software Community",
                    "url": "http://oss.deltares.nl/web/delft-fews/",
                    "localRun": True,
                    "showRunApprovedForecastButton": False,
                },
            ],
        },
    ],
}


# Mapping from import-workflow prefix to (group_id, group_name,
# grace_hours). Order matters — first match wins.
_IMPORT_CATEGORIES: list[tuple[re.Pattern[str], str, str, int]] = [
    (re.compile(r"^Import(?:HRDPS|RDPS|GDPS|REPS|RDPA|HRDPA)"),
     "ImportECCCGridNodes", "Import ECCC Forecasts", 6),
    (re.compile(r"^Import(?:GFS|NAM|SREF|GEFS)"),
     "ImportNOAAGridNodes", "Import NOAA Forecasts", 6),
    (re.compile(r"^ImportE2O"),
     "ImportHistoricGrid", "Import Historic Gridded Data", 24),
    (re.compile(r"^ImportWSC"),
     "ImportWSC", "Import WSC Hydrological Data", 24),
    (re.compile(r"^ImportECCC(?!.*Grids)"),
     "ImportECCCStationNodes", "Import ECCC Meteo Data", 24),
    (re.compile(r"^Import(?:GLOBSNOW|SNODAS|GPM|GSMAP)"),
     "ImportSnow", "Import Snow Data", 24),
]

# Run-workflow split: filenames are Run<Model><Type> where Type is
# Historic or <NWP>Forecast. Capture both.
_RUN_RE = re.compile(r"^Run(?P<model>[A-Za-z0-9$_]+?)(?P<type>Historic|[A-Z]+Forecast)$")


def _collect_workflow_stems(
    rendered_files: list["RenderedFile"],
) -> list[str]:
    """Return workflow IDs (stems of WorkflowFiles/*.xml)."""
    stems: list[str] = []
    for rf in rendered_files:
        if "WorkflowFiles" not in rf.relpath.replace("\\", "/"):
            continue
        stem = Path(rf.relpath).stem
        if stem and not stem.lower().startswith("preprocess"):
            stems.append(stem)
    return stems


def _categorize_imports(stems: list[str]) -> list[dict[str, Any]]:
    """Group Import* workflow stems into topology import groups."""
    buckets: dict[str, list[str]] = {}
    meta: dict[str, tuple[str, int]] = {}
    for stem in stems:
        if not stem.startswith("Import"):
            continue
        for pat, group_id, group_name, grace in _IMPORT_CATEGORIES:
            if pat.match(stem):
                buckets.setdefault(group_id, []).append(stem)
                meta[group_id] = (group_name, grace)
                break

    groups: list[dict[str, Any]] = []
    for group_id, members in buckets.items():
        group_name, grace_hours = meta[group_id]
        leaves = []
        for stem in sorted(members):
            # Strip trailing "Grids" for cleaner leaf names where present.
            leaf_id = stem.removesuffix("Grids") if stem.endswith("Grids") else stem
            leaves.append({
                "id": leaf_id,
                "name": f"Import {leaf_id.removeprefix('Import')}",
                "workflowId": stem,
                "graceTime": {"unit": "hour", "multiplier": grace_hours},
                "localRun": True,
                "showRunApprovedForecastButton": True,
            })
        groups.append({
            "id": group_id,
            "name": group_name,
            "node": leaves,
        })
    return groups


def _categorize_runs(stems: list[str]) -> list[dict[str, Any]]:
    """Group Run* workflow stems by model name into topology run groups."""
    buckets: dict[str, list[tuple[str, str]]] = {}  # model -> [(stem, type)]
    for stem in stems:
        m = _RUN_RE.match(stem)
        if not m:
            continue
        model = m.group("model")
        run_type = m.group("type")
        buckets.setdefault(model, []).append((stem, run_type))

    groups: list[dict[str, Any]] = []
    for model, entries in buckets.items():
        # Sort: Historic first, then alphabetical forecasts.
        entries.sort(key=lambda x: (0 if x[1] == "Historic" else 1, x[1]))
        leaves = []
        for stem, run_type in entries:
            display_type = "Historic" if run_type == "Historic" else run_type.replace("Forecast", " Forecast")
            leaves.append({
                "id": stem.removeprefix("Run"),
                "name": f"Run {model} {display_type}",
                "workflowId": stem,
                "localRun": True,
                "showRunApprovedForecastButton": True,
            })
        groups.append({
            "id": f"{model}Nodes",
            "name": f"Run {model}",
            "node": leaves,
        })
    return groups


def derive_topology_yaml(
    rendered_files: list["RenderedFile"],
) -> dict[str, Any] | None:
    """Build a topology.yaml-shaped dict from rendered workflow files.

    Returns ``None`` if no workflows are present (nothing to navigate).
    """
    stems = _collect_workflow_stems(rendered_files)
    if not stems:
        return None

    nodes: list[dict[str, Any]] = [_INFORMATION_SOURCES]
    nodes.extend(_categorize_imports(stems))
    nodes.extend(_categorize_runs(stems))

    return {
        "enableAutoRun": False,
        "enableAutoSelectParameters": True,
        "enableSelectNodesFromMap": False,
        "nodes": nodes,
    }


__all__ = ["derive_topology_yaml"]
