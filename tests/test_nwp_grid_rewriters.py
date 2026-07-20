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
    _apply_grid_geometry_to_grids,
    _apply_nwp_resolutions_to_grids,
    _apply_region_to_grids,
    _nwp_geometries_from_blueprint,
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


# --- explicit grid geometry (/coordinates): point + rows, inherit cell size --

_GEOM = {"first_x": -11.75, "first_y": 8.75, "columns": 48, "rows": 30}


def test_grid_geometry_stamps_point_and_counts_inherits_cell_size():
    # A configurator-set geometry rides on the instance for ANY nwp_grid_*
    # source (here ECCC HRDPS at its 0.0225 native cell size).
    bp = _bp(("auto/nwp_grid_eccc_HRDPS",
              [{"nwp_name": "HRDPS", "grid_geometry": _GEOM}]))
    geos = _nwp_geometries_from_blueprint(bp)
    assert geos == {"HRDPS": _GEOM}

    data = _grids({"@locationId": "HRDPS", "rows": "100", "columns": "100",
                   "firstCellCenter": {"x": "0", "y": "0"},
                   "xCellSize": "0.0225", "yCellSize": "0.0225"})
    inner = _apply_grid_geometry_to_grids(data, geos)["body"][0]["regular"]
    # firstCellCenter + counts stamped...
    assert inner["rows"] == "30" and inner["columns"] == "48"
    assert inner["firstCellCenter"] == {"x": "-11.75", "y": "8.75"}
    # ...cell size inherited (NOT touched).
    assert inner["xCellSize"] == "0.0225" and inner["yCellSize"] == "0.0225"


def test_grid_geometry_wins_over_region_crop():
    # Region crop then geometry: the explicit point/counts must survive.
    geos = {"GFS": _GEOM}
    data = _grids({"@locationId": "GFS", "xCellSize": "0.5", "yCellSize": "0.5",
                   "rows": "9", "columns": "9",
                   "firstCellCenter": {"x": "0", "y": "0"}})
    cropped = _apply_region_to_grids(data, "Gulf of Guinea", {"GFS"})
    final = _apply_grid_geometry_to_grids(cropped, geos)["body"][0]["regular"]
    assert final["rows"] == "30" and final["columns"] == "48"
    assert final["firstCellCenter"] == {"x": "-11.75", "y": "8.75"}


def test_grid_geometry_skips_projected_and_foreign_grids():
    geos = {"GFS": _GEOM}
    data = _grids(
        # polarStereographic grid — no firstCellCenter, must be left alone.
        {"@locationId": "GFS", "rows": "800", "columns": "900",
         "polarStereographic": {"originLatitude": "90.0"}},
        # a different source — not in the geometry map.
        {"@locationId": "RDPS", "rows": "50", "columns": "50",
         "firstCellCenter": {"x": "1", "y": "2"},
         "xCellSize": "0.1", "yCellSize": "0.1"},
    )
    out = _apply_grid_geometry_to_grids(data, geos)["body"]
    assert out[0]["regular"]["rows"] == "800"          # projected untouched
    assert out[1]["regular"]["firstCellCenter"] == {"x": "1", "y": "2"}  # foreign


def test_grid_geometry_extractor_ignores_malformed():
    bp = _bp(("auto/nwp_grid_noaa",
              [{"nwp_name": "GFS", "grid_geometry": {"first_x": 1}}]))  # incomplete
    assert _nwp_geometries_from_blueprint(bp) == {}


def test_set_grid_geometry_mutator_scopes_to_named_import():
    from fews_agent.agent.project_chat import set_grid_geometry
    state = {"slots": {"imports": ["GFS", "HRDPS"]}}
    note = set_grid_geometry(state, "hrdps", first_x=-11.75, first_y=8.75,
                             columns=48, rows=30)
    assert "HRDPS" in note
    ov = state["slots"]["import_overrides"]
    assert ov["HRDPS"]["grid_geometry"] == _GEOM
    assert "GFS" not in ov  # scoped to the named import only


def test_grid_bbox_from_firstcellcenter_and_counts():
    from fews_agent.agent.project_chat import grid_bbox
    # firstCellCenter is the CENTRE of the NW cell → edges sit half a cell out;
    # rows run south.
    west, south, east, north = grid_bbox(-11.75, 8.75, 48, 30, 0.5)
    assert (west, south, east, north) == (-12.0, -6.0, 12.0, 9.0)
    # A 1x1 grid's box is exactly one cell centred on the point.
    assert grid_bbox(0.0, 0.0, 1, 1, 2.0) == (-1.0, -1.0, 1.0, 1.0)
