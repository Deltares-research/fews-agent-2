"""Build-side NWP grid rewriters: region-bbox crop + resolution override.

Pins the *source coverage* of each rewriter, which is easy to get wrong
(the CLAUDE.md note once claimed the whole bbox/resolution/horizon
mechanism was "NOAA-only" — only the resolution + parameter-selection
legs are). No LLM, no full build: these are pure dict->dict rewrites.

- **bbox crop** keys on the ``auto/nwp_grid_`` *prefix*, so it already
  covers ECCC (HRDPS/GDPS/RDPS), not just NOAA GFS.
- **resolution override** is NOAA-shaped: it only fires for an instance
  carrying a known ``grid_resolution`` slug (0p25/0p50/1p00). ECCC
  products are fixed native resolution (no slug), so it correctly
  no-ops on them.
- both leave user-authored grid entries untouched.
"""
from __future__ import annotations

from types import SimpleNamespace

from runners.agent.build_from_blueprint import (
    _apply_nwp_resolutions_to_grids,
    _apply_region_to_grids,
    _nwp_location_ids_from_blueprint,
    _nwp_resolutions_from_blueprint,
)


def _bp(*pattern_instances):
    """A blueprint stub: [(pattern_path, [instance_dict, ...]), ...]."""
    return SimpleNamespace(patterns=[
        SimpleNamespace(pattern=path, instances=list(insts))
        for path, insts in pattern_instances
    ])


def _grids(*entries):
    """A gridsFile-shaped body of ``regular`` entries."""
    return {"body": [{"regular": dict(e)} for e in entries]}


# --- bbox crop reaches ECCC, not just NOAA --------------------------------

def test_bbox_crop_covers_eccc_grids():
    # An ECCC-only project (no NOAA anywhere).
    bp = _bp(("auto/nwp_grid_eccc_HRDPS", [{"nwp_name": "HRDPS"}]))
    ids = _nwp_location_ids_from_blueprint(bp)
    assert ids == {"HRDPS"}

    data = _grids(
        {"@locationId": "HRDPS", "xCellSize": "0.5", "yCellSize": "0.5",
         "rows": "100", "columns": "100"},
        {"@locationId": "UserGrid", "xCellSize": "0.5", "yCellSize": "0.5",
         "rows": "9", "columns": "9"},
    )
    out = _apply_region_to_grids(data, "Gulf of Guinea", ids)
    hrdps = out["body"][0]["regular"]
    user = out["body"][1]["regular"]

    # HRDPS recomputed to the region bbox...
    assert hrdps["rows"] != "100" and hrdps["columns"] != "100"
    assert "firstCellCenter" in hrdps
    # ...user grid untouched (not an NWP locationId).
    assert user["rows"] == "9" and "firstCellCenter" not in user


def test_bbox_crop_collects_multiple_eccc_sources():
    bp = _bp(
        ("auto/nwp_grid_eccc_GDPS", [{"nwp_name": "GDPS"}]),
        ("auto/nwp_grid_eccc_RDPS", [{"nwp_name": "RDPS"}]),
        ("auto/nwp_grid_noaa", [{"nwp_name": "GFS"}]),
    )
    assert _nwp_location_ids_from_blueprint(bp) == {"GDPS", "RDPS", "GFS"}


# --- resolution override is NOAA-shaped (slug-gated), correctly ------------

def test_resolution_override_applies_to_slugged_noaa_instance():
    bp = _bp(("auto/nwp_grid_noaa", [{"nwp_name": "GFS", "grid_resolution": "0p50"}]))
    res = _nwp_resolutions_from_blueprint(bp)
    assert res == {"GFS": 0.5}

    data = _grids({"@locationId": "GFS", "xCellSize": "0.25", "yCellSize": "0.25"})
    out = _apply_nwp_resolutions_to_grids(data, res)
    inner = out["body"][0]["regular"]
    assert inner["xCellSize"] == "0.5" and inner["yCellSize"] == "0.5"


def test_resolution_override_noops_on_eccc_without_slug():
    # ECCC products carry no grid_resolution slug (fixed native resolution),
    # so the resolution map is empty and the grid is left as-is.
    bp = _bp(("auto/nwp_grid_eccc_HRDPS", [{"nwp_name": "HRDPS"}]))
    assert _nwp_resolutions_from_blueprint(bp) == {}

    data = _grids({"@locationId": "HRDPS", "xCellSize": "0.0225", "yCellSize": "0.0225"})
    out = _apply_nwp_resolutions_to_grids(data, _nwp_resolutions_from_blueprint(bp))
    assert out["body"][0]["regular"]["xCellSize"] == "0.0225"


def test_resolution_override_ignores_unknown_slug():
    bp = _bp(("auto/nwp_grid_noaa", [{"nwp_name": "GFS", "grid_resolution": "9p99"}]))
    assert _nwp_resolutions_from_blueprint(bp) == {}
