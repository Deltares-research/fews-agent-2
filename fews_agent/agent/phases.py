"""Capability-group ("phase") taxonomy for module-by-module building.

The build path can render a whole project in one shot, but the *guided*
flow walks the user through one capability group at a time:

    imports  →  process  →  model  →  visualize

Each phase is a coarse grouping of patterns by what the configurator is
trying to accomplish at that step. A phase is built and XSD-validated on
its own (just that phase's pattern outputs), so the user sees concrete,
valid files for one capability before moving to the next. The full
cross-file assembly (singleton merge, bundled standards, derivers,
semantic cross-reference check) is deferred to final assembly (``done``).

This module is the single source of truth for "which pattern belongs to
which phase". `classify_phase` is deterministic and name-based — no LLM.
"""
from __future__ import annotations

from typing import Any

# Ordered phases. The guided flow walks them in this order; an empty
# phase (no patterns resolved for it) is simply skipped.
PHASE_ORDER: list[str] = ["imports", "process", "model", "visualize", "maintenance"]

# Human-facing one-liners — used in the phase plan shown to the user.
PHASE_LABELS: dict[str, str] = {
    "imports": "Import external data (NWP grids, satellite, snow, scalar)",
    "process": "Prepare data (preprocess / merge / modify / postprocess)",
    "model": "Run a basin model (Raven, Wflow, ...)",
    "visualize": "Visualize (Spatial Display, grid display, plots)",
    "maintenance": "Housekeeping (amalgamate, archive, system metrics)",
}


def classify_phase(pattern_path: str) -> str:
    """Map a pattern path (e.g. ``auto/gfs/deterministic``) to a phase.

    Name-based and deterministic. The order of checks matters:
    visualize / model / process are matched before the import catch-all
    so a display or model pattern never falls through to ``imports``.
    """
    name = pattern_path.rsplit("/", 1)[-1].lower()

    # Visualization: spatial/grid display, plots, map layers.
    if (
        name.startswith(("spatial_display", "grid_display", "map_layer"))
        or "display" in name
        or "visuali" in name
        or "spatial" in name
    ):
        return "visualize"

    # Models: a basin/model run (hydrological or coastal).
    if (
        name in {"raven_basin", "wflow_basin"}
        or name.endswith("_basin")
        or name.endswith("_model")
        or name.startswith(("raven", "wflow", "hbv", "coastal_"))
        or "dflowfm" in name
        or "delft3d" in name
    ):
        return "model"

    # Data preparation: preprocess/merge/modify/update templates and
    # workflows that act on already-imported data.
    if (
        name.startswith("tpl_")
        or name.startswith(("wf_merge", "wf_modify", "wf_update"))
        or "preprocess" in name
        or "postprocess" in name
        or "interpolate" in name
        or "accumulate" in name
    ):
        return "process"

    # Maintenance / housekeeping: amalgamate, archive, system metrics.
    if (
        "amalgamate" in name
        or "archive" in name
        or "maintenance" in name
        or "metrics" in name
    ):
        return "maintenance"

    # Everything else is treated as an import (the default bucket):
    # nwp_grid_*, satellite_precip_*, snow_import_*, earth2observe,
    # eccc_scalar, wsc_scalar_*, wf_import_*.
    return "imports"


def phase_plan(patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group resolved pattern instances into an ordered phase plan.

    ``patterns`` is ``state["patterns"]`` — a list of dicts each with a
    ``pattern`` path and ``instances``. Returns one entry per non-empty
    phase, in PHASE_ORDER, each with the patterns and instance count.
    """
    buckets: dict[str, list[dict[str, Any]]] = {p: [] for p in PHASE_ORDER}
    for entry in patterns or []:
        path = entry.get("pattern", "")
        buckets[classify_phase(path)].append(entry)

    plan: list[dict[str, Any]] = []
    for phase in PHASE_ORDER:
        members = buckets[phase]
        if not members:
            continue
        n_instances = sum(len(m.get("instances") or [{}]) for m in members)
        plan.append({
            "phase": phase,
            "label": PHASE_LABELS[phase],
            "patterns": members,
            "pattern_count": len(members),
            "instance_count": n_instances,
        })
    return plan


def next_unbuilt_phase(
    patterns: list[dict[str, Any]], built: list[str] | None,
) -> str | None:
    """Return the first phase that has patterns but hasn't been built yet."""
    built_set = set(built or [])
    for entry in phase_plan(patterns):
        if entry["phase"] not in built_set:
            return entry["phase"]
    return None


def normalize_phase(token: str) -> str | None:
    """Resolve a user-typed phase token to a canonical phase name.

    Accepts synonyms (``import`` → ``imports``, ``viz`` → ``visualize``,
    ``models`` → ``model``, ``preprocess`` → ``process``).
    """
    t = (token or "").strip().lower()
    synonyms = {
        "import": "imports",
        "imports": "imports",
        "data": "imports",
        "process": "process",
        "processing": "process",
        "preprocess": "process",
        "prepare": "process",
        "model": "model",
        "models": "model",
        "basin": "model",
        "run": "model",
        "visualize": "visualize",
        "visualise": "visualize",
        "viz": "visualize",
        "display": "visualize",
        "spatial": "visualize",
        "maintenance": "maintenance",
        "maintain": "maintenance",
        "housekeeping": "maintenance",
        "amalgamate": "maintenance",
        "archive": "maintenance",
    }
    return synonyms.get(t)
