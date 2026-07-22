"""The slot-patch op vocabulary — the trust boundary of the LLM-first turn.

Everything here is deterministic (no LLM): each op validates against the
catalog, applies through the existing slot machinery, and rejects loudly.
These tests are the contract the model's patches are held to.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fews_agent.agent.patch_ops import apply_patch
from fews_agent.agent.project_chat import build_pattern_catalog

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalog():
    return build_pattern_catalog(REPO / "fews_agent" / "patterns")


@pytest.fixture()
def state():
    return {"slots": {}, "current_module": "processing",
            "intent": "build_data_import_only"}


# --- add_import -----------------------------------------------------------

def test_add_import_applies_and_resolves(state, catalog):
    res = apply_patch(state, [{"op": "add_import", "name": "GFS"}], catalog)
    assert res.dropped == []
    assert "GFS" in state["slots"]["imports"]
    assert any("GFS" in n for n in res.notes)
    assert "auto/nwp_grid_noaa" in {p["pattern"] for p in state["patterns"]}


def test_add_import_accepts_aliases_case_insensitively(state, catalog):
    apply_patch(state, [{"op": "add_import", "name": "gfs"}], catalog)
    assert "GFS" in state["slots"]["imports"]


def test_add_import_unknown_is_dropped_loudly(state, catalog):
    res = apply_patch(
        state, [{"op": "add_import", "name": "MysteryModel"}], catalog,
    )
    assert state["slots"].get("imports") in (None, [])
    assert any("MysteryModel" in d for d in res.dropped)


def test_add_import_with_scoped_scalars(state, catalog):
    res = apply_patch(state, [{
        "op": "add_import", "name": "GFS",
        "data_types": ["precipitation"], "grid_resolution": "0p50",
        "forecast_horizon_hours": 168,
    }], catalog)
    assert res.dropped == []
    assert state["slots"]["data_types"] == ["precipitation"]
    ov = state["slots"]["import_overrides"]["GFS"]
    assert ov["grid_resolution"] == "0p50"
    assert ov["forecast_horizon_hours"] == 168


def test_add_import_hallucinated_data_type_dropped_import_kept(state, catalog):
    res = apply_patch(state, [{
        "op": "add_import", "name": "GFS", "data_types": ["unobtainium"],
    }], catalog)
    assert "GFS" in state["slots"]["imports"]
    assert any("unobtainium" in d for d in res.dropped)


# --- add_basin (the Rhine rule) -------------------------------------------

def test_add_basin_with_valid_adapter(state, catalog):
    res = apply_patch(state, [{
        "op": "add_basin", "basin_name": "Rhine", "model_adapter": "hbv96",
    }], catalog)
    assert res.dropped == []
    assert state["slots"]["basins"] == [
        {"basin_name": "Rhine", "model_adapter": "hbv96"}
    ]


def test_add_basin_guessed_adapter_is_refused(state, catalog):
    """The model must ASK for the adapter, never guess — a bogus one is
    rejected with the known options in the error, so it can self-correct."""
    res = apply_patch(state, [{
        "op": "add_basin", "basin_name": "Rhine", "model_adapter": "sobek",
    }], catalog)
    assert state["slots"].get("basins") in (None, [])
    assert any("sobek" in d and "raven" in d for d in res.dropped)


def test_add_basin_without_adapter_is_refused(state, catalog):
    res = apply_patch(
        state, [{"op": "add_basin", "basin_name": "Rhine"}], catalog,
    )
    assert state["slots"].get("basins") in (None, [])
    assert res.dropped


# --- add_capability -------------------------------------------------------

def test_add_capability_by_name_or_path(state, catalog):
    apply_patch(state, [{"op": "add_capability",
                         "pattern": "coastal_sfincs"}], catalog)
    assert "auto/coastal_sfincs" in state["slots"]["extra_patterns"]
    assert "auto/coastal_sfincs" in {p["pattern"] for p in state["patterns"]}


def test_add_capability_needing_input_reports_vars(state, catalog):
    res = apply_patch(state, [{"op": "add_capability",
                               "pattern": "archive_import"}], catalog)
    assert state["slots"].get("extra_patterns") in (None, [])
    assert any("archive_root" in d for d in res.dropped)


def test_add_capability_unknown_dropped(state, catalog):
    res = apply_patch(state, [{"op": "add_capability",
                               "pattern": "quantum_flux"}], catalog)
    assert any("quantum_flux" in d for d in res.dropped)


# --- set_variables --------------------------------------------------------

def test_set_variables_scoped_to_an_import(state, catalog):
    apply_patch(state, [{"op": "add_import", "name": "GFS"}], catalog)
    res = apply_patch(state, [{
        "op": "set_variables", "target": "GFS",
        "values": {"grid_resolution": "half degree"},
    }], catalog)
    assert res.dropped == []
    assert state["slots"]["import_overrides"]["GFS"]["grid_resolution"] == "0p50"


def test_set_variables_grid_geometry(state, catalog):
    apply_patch(state, [{"op": "add_import", "name": "GFS"}], catalog)
    res = apply_patch(state, [{
        "op": "set_variables", "target": "GFS",
        "values": {"grid_geometry": {
            "first_x": -11.75, "first_y": 8.75, "columns": 48, "rows": 30,
        }},
    }], catalog)
    assert res.dropped == []
    geom = state["slots"]["import_overrides"]["GFS"]["grid_geometry"]
    assert geom["columns"] == 48


def test_set_variables_bad_value_dropped(state, catalog):
    res = apply_patch(state, [{
        "op": "set_variables", "target": "GFS",
        "values": {"grid_resolution": "seventeen degrees"},
    }], catalog)
    assert any("seventeen degrees" in d for d in res.dropped)


# --- remove ---------------------------------------------------------------

def test_remove_import_basin_datatype_capability(state, catalog):
    apply_patch(state, [
        {"op": "add_import", "name": "GFS", "data_types": ["temperature"]},
        {"op": "add_basin", "basin_name": "Liard", "model_adapter": "raven"},
        {"op": "add_capability", "pattern": "coastal_sfincs"},
    ], catalog)
    res = apply_patch(state, [
        {"op": "remove", "target": "temperature"},
        {"op": "remove", "target": "Liard"},
        {"op": "remove", "target": "coastal_sfincs"},
        {"op": "remove", "target": "GFS"},
    ], catalog)
    assert res.dropped == []
    s = state["slots"]
    assert s.get("imports") in (None, [])
    assert s.get("basins") in (None, [])
    assert "temperature" not in (s.get("data_types") or [])
    assert s.get("extra_patterns") in (None, [])


def test_remove_unknown_target_dropped(state, catalog):
    res = apply_patch(state, [{"op": "remove", "target": "Narnia"}], catalog)
    assert any("Narnia" in d for d in res.dropped)


# --- focus / signals / batch ----------------------------------------------

def test_set_focus_normalizes_synonyms(state, catalog):
    res = apply_patch(state, [{"op": "set_focus", "module": "imports"}], catalog)
    assert res.dropped == []
    assert state["current_module"] == "processing"


def test_signals_do_not_mutate_state(state, catalog):
    before = dict(state["slots"])
    res = apply_patch(state, [
        {"op": "build", "scope": "imports"},
        {"op": "open_coordinates", "name": "GFS"},
        {"op": "assemble"},
        {"op": "none"},
    ], catalog)
    assert state["slots"] == before
    assert res.wants_build and res.build_scope == "imports"
    assert res.coordinates_for == "GFS"
    assert res.wants_assemble


def test_mixed_batch_applies_valid_drops_invalid(state, catalog):
    res = apply_patch(state, [
        {"op": "add_import", "name": "GFS"},
        {"op": "add_import", "name": "MysteryModel"},
        {"op": "frobnicate"},
        "not even a dict",
    ], catalog)
    assert "GFS" in state["slots"]["imports"]
    assert len(res.dropped) == 3


def test_compound_swap_in_one_patch(state, catalog):
    """The single-call payoff: 'swap GFS for ECMWF at half degree' is ONE
    patch."""
    apply_patch(state, [{"op": "add_import", "name": "GFS"}], catalog)
    res = apply_patch(state, [
        {"op": "remove", "target": "GFS"},
        {"op": "add_import", "name": "ECMWF", "grid_resolution": "0p50"},
    ], catalog)
    assert res.dropped == []
    assert state["slots"]["imports"] == ["ECMWF"]


# --- variable unset + feature flags (hard-scenario support) ---------------

def test_remove_scoped_variable_clears_the_override(state, catalog):
    apply_patch(state, [{"op": "add_import", "name": "GFS",
                         "grid_resolution": "0p50",
                         "forecast_horizon_hours": 168}], catalog)
    res = apply_patch(state, [
        {"op": "remove", "target": "GFS", "variable": "forecast_horizon_hours"},
    ], catalog)
    assert res.dropped == []
    ov = state["slots"]["import_overrides"]["GFS"]
    assert "forecast_horizon_hours" not in ov
    assert ov["grid_resolution"] == "0p50"          # untouched


def test_remove_projectwide_variable_sweeps_overrides(state, catalog):
    apply_patch(state, [
        {"op": "add_import", "name": "GFS", "grid_resolution": "0p50"},
        {"op": "add_import", "name": "HRDPS"},
    ], catalog)
    state["slots"]["grid_resolution"] = "0p25"      # project default too
    res = apply_patch(state, [{"op": "remove", "target": "grid_resolution"}],
                      catalog)
    assert res.dropped == []
    assert "grid_resolution" not in state["slots"]
    assert "grid_resolution" not in state["slots"]["import_overrides"]["GFS"]


def test_remove_variable_with_nothing_set_is_reported(state, catalog):
    apply_patch(state, [{"op": "add_import", "name": "GFS"}], catalog)
    res = apply_patch(state, [
        {"op": "remove", "target": "GFS", "variable": "horizon"},
    ], catalog)
    assert any("no forecast_horizon_hours" in d for d in res.dropped)


def test_visualization_flag_resolves_display_pattern(state, catalog):
    apply_patch(state, [
        {"op": "add_import", "name": "GFS"},
        {"op": "set_variables", "target": "",
         "values": {"wants_visualization": True}},
    ], catalog)
    assert state["slots"].get("wants_visualization") is True
    assert "auto/spatial_display_grid" in {
        p["pattern"] for p in state["patterns"]
    }


def test_interpolation_flag_resolves_interpolate_pattern(state, catalog):
    # The resolver's contract: interpolation needs BOTH the flag AND selected
    # weather variables (it intersects them per import) — so the flag alone
    # resolves nothing, which is correct, not a gap.
    apply_patch(state, [
        {"op": "add_import", "name": "GFS", "data_types": ["precipitation"]},
        {"op": "set_variables", "target": "",
         "values": {"wants_interpolation": True}},
    ], catalog)
    assert "auto/wf_interpolate_nwp_to_stations" in {
        p["pattern"] for p in state["patterns"]
    }


# --- live-found bugs (hard-scenario round) --------------------------------

def test_remove_with_datatype_variable_never_deletes_the_import(state, catalog):
    """LIVE BUG: remove {target:"GFS", variable:"temperature"} ignored the
    variable and deleted the whole GFS import. `variable` is authoritative:
    handle it fully or drop the op — never fall through."""
    apply_patch(state, [{"op": "add_import", "name": "GFS",
                         "data_types": ["precipitation", "temperature"]}],
                catalog)
    res = apply_patch(state, [
        {"op": "remove", "target": "GFS", "variable": "temperature"},
    ], catalog)
    assert state["slots"]["imports"] == ["GFS"]          # import SURVIVES
    assert state["slots"]["data_types"] == ["precipitation"]
    assert res.dropped == []


def test_remove_with_unknown_variable_drops_not_falls_through(state, catalog):
    apply_patch(state, [{"op": "add_import", "name": "GFS"}], catalog)
    res = apply_patch(state, [
        {"op": "remove", "target": "GFS", "variable": "frobnication"},
    ], catalog)
    assert state["slots"]["imports"] == ["GFS"]          # import SURVIVES
    assert any("frobnication" in d for d in res.dropped)


def test_set_variables_geodatum_and_region_sync_singleton(state, catalog):
    res = apply_patch(state, [
        {"op": "set_variables", "target": "",
         "values": {"geoDatum": "WGS 1984", "region": "Gulf of Guinea"}},
    ], catalog)
    assert res.dropped == []
    assert state["slots"]["geoDatum"] == "WGS 1984"
    assert state["slots"]["region"] == "Gulf of Guinea"
    seed = state["singleton_seeds"]["Locations"]
    assert seed["geoDatum"] == "WGS 1984"
    assert seed["region"] == "Gulf of Guinea"


def test_add_capability_redirects_flag_owned_patterns(state, catalog):
    """spatial_display_grid / wf_interpolate are emitted by the resolvers per
    eligible import — adding them directly used to be refused (required
    vars). Any route the model picks must now work."""
    apply_patch(state, [{"op": "add_import", "name": "GFS",
                         "data_types": ["precipitation"]}], catalog)
    res = apply_patch(state, [
        {"op": "add_capability", "pattern": "spatial_display_grid"},
        {"op": "add_capability", "pattern": "wf_interpolate_nwp_to_stations"},
    ], catalog)
    assert res.dropped == []
    assert state["slots"].get("wants_visualization") is True
    assert state["slots"].get("wants_interpolation") is True
    got = {p["pattern"] for p in state["patterns"]}
    assert "auto/spatial_display_grid" in got
    assert "auto/wf_interpolate_nwp_to_stations" in got
    assert "auto/spatial_display_grid" not in (
        state["slots"].get("extra_patterns") or []
    )


def test_add_capability_redirects_import_owned_patterns(state, catalog):
    """LIVE BUG: 'add GFS and HRDPS' routed HRDPS through
    add_capability nwp_grid_eccc_HRDPS, which refused (needs nwp_name).
    Import-owned patterns redirect to add_import so any route works."""
    res = apply_patch(state, [
        {"op": "add_capability", "pattern": "nwp_grid_eccc_HRDPS"},
    ], catalog)
    assert res.dropped == []
    assert "HRDPS" in state["slots"]["imports"]


def test_show_variables_signal(state, catalog):
    res = apply_patch(state, [{"op": "show_variables", "target": "GFS"}],
                      catalog)
    assert res.vars_for == "GFS"
    res2 = apply_patch(state, [{"op": "show_variables"}], catalog)
    assert res2.vars_for == ""


def test_set_focus_note_speaks_the_fews_label(state, catalog):
    """LIVE BUG (PDF): the grey note said 'Focused the filters module.' —
    internal key. It must speak the FEWS folder label."""
    res = apply_patch(state, [{"op": "set_focus", "module": "filters"}],
                      catalog)
    assert res.notes == ["Focused on RegionConfigFiles · Filters."]
