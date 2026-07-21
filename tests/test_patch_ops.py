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
    return build_pattern_catalog(REPO / "patterns")


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
