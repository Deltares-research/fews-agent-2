"""Tests for the module-mode operation extractor (P2 slice).

The LLM is stubbed, so these assert the deterministic half: the trust
boundary (catalog validation dropping hallucinations, canonicalizing
aliases) and the action/module routing. No live model.
"""
from __future__ import annotations

from fews_agent.agent import extractor as E
from fews_agent.agent import modules as M


PROC = M.get_module("processing")


class _Resp:
    def __init__(self, data):
        self.data = data


class _Provider:
    """Returns a fixed JSON payload for generate_json."""

    def __init__(self, data):
        self._data = data

    def generate_json(self, system, user, schema):
        return _Resp(self._data)


class _BoomProvider:
    def generate_json(self, *a, **k):
        raise RuntimeError("provider down")


def _run(payload, message="do it"):
    return E.extract_operation(
        message, focus_module=PROC, provider=_Provider(payload)
    )


# --- validation: the trust boundary ---------------------------------------

def test_valid_add_maps_to_fields():
    op = _run({"action": "add",
               "fields": {"imports": ["GFS"], "data_types": ["precipitation"]}})
    assert op.action == "add"
    assert op.fields["imports"] == ["GFS"]
    assert op.fields["data_types"] == ["precipitation"]
    assert op.dropped == []


def test_hallucinated_import_is_dropped_not_applied():
    op = _run({"action": "add",
               "fields": {"imports": ["GFS", "GFS2", "MadeUpModel"]}})
    assert op.fields["imports"] == ["GFS"]           # only the real one kept
    assert "import:GFS2" in op.dropped
    assert "import:MadeUpModel" in op.dropped


def test_import_aliases_are_canonicalized():
    op = _run({"action": "add", "fields": {"imports": ["IFS", "WSC", "GHCN"]}})
    # IFS -> ECMWF, WSC -> WSCHourly, GHCN -> GHCND (from _IMPORT_ALIASES).
    assert set(op.fields["imports"]) == {"ECMWF", "WSCHourly", "GHCND"}
    assert op.dropped == []


def test_unknown_data_type_dropped():
    op = _run({"action": "add",
               "fields": {"data_types": ["precipitation", "unicorns"]}})
    assert op.fields["data_types"] == ["precipitation"]
    assert "data_type:unicorns" in op.dropped


def test_grid_resolution_prose_is_mapped_else_dropped():
    ok = _run({"action": "set", "fields": {"grid_resolution": "quarter degree"}})
    assert ok.fields["grid_resolution"] == "0p25"
    bad = _run({"action": "set", "fields": {"grid_resolution": "ultra-fine"}})
    assert "grid_resolution" not in bad.fields
    assert any(d.startswith("grid_resolution:") for d in bad.dropped)


def test_forecast_horizon_coerced():
    op = _run({"action": "set", "fields": {"forecast_horizon_hours": "168"}})
    assert op.fields["forecast_horizon_hours"] == 168


def test_basin_with_unknown_adapter_dropped():
    op = _run({"action": "add",
               "fields": {"basins": [
                   {"basin_name": "Liard", "model_adapter": "raven"},
                   {"basin_name": "Ghost", "model_adapter": "nonsense"},
               ]}})
    assert op.fields["basins"] == [
        {"basin_name": "Liard", "model_adapter": "raven"}
    ]
    assert "adapter:nonsense" in op.dropped


# --- action / module routing ----------------------------------------------

def test_select_module_normalizes_target():
    op = _run({"action": "select_module", "module": "spatial"})
    assert op.action == "select_module"
    assert op.module == "display"


def test_select_module_unknown_target_becomes_none():
    op = _run({"action": "select_module", "module": "banana"})
    assert op.action == "none"
    assert op.module is None


def test_unknown_action_falls_back_to_none():
    op = _run({"action": "frobnicate", "fields": {}})
    assert op.action == "none"


def test_provider_error_yields_none_action():
    op = E.extract_operation(
        "do it", focus_module=PROC, provider=_BoomProvider()
    )
    assert op.action == "none"
    assert op.fields == {}


def test_fields_are_slot_shaped_for_reuse():
    # fields must be the SAME shape extract_skills produces, so add/set can
    # flow through the existing additive slot-fill unchanged.
    op = _run({"action": "add",
               "fields": {"imports": ["HRDPS"], "region": "North Sea",
                          "wants_visualization": True}})
    assert op.fields["imports"] == ["HRDPS"]
    assert op.fields["region"] == "North Sea"
    assert op.fields["wants_visualization"] is True


# --- applying an operation (turn_engine helpers) --------------------------

from pathlib import Path

from fews_agent.agent.project_chat import build_pattern_catalog
from fews_agent.agent.turn_engine import (
    apply_extracted_fields,
    extracted_removal_edits,
)

_CATALOG = build_pattern_catalog(Path(__file__).resolve().parents[1] / "patterns")


class _Op:
    def __init__(self, action, fields):
        self.action = action
        self.fields = fields


def test_apply_add_merges_and_resolves():
    state = {"slots": {}, "patterns": []}
    note, new = apply_extracted_fields(state, _Op("add", {"imports": ["GFS"]}), _CATALOG)
    assert state["slots"]["imports"] == ["GFS"]
    assert any("nwp_grid_noaa" in p for p in new)
    # No basin + imports → the heuristic infers the data-import intent.
    assert state["intent"] == "build_data_import_only"


def test_apply_set_overrides_scalar():
    state = {"slots": {"grid_resolution": "0p25"}, "patterns": [],
             "intent": "build_data_import_only"}
    apply_extracted_fields(state, _Op("set", {"grid_resolution": "0p50"}), _CATALOG)
    assert state["slots"]["grid_resolution"] == "0p50"


def test_apply_add_does_not_override_existing_scalar():
    state = {"slots": {"grid_resolution": "0p25"}, "patterns": [],
             "intent": "build_data_import_only"}
    apply_extracted_fields(state, _Op("add", {"grid_resolution": "0p50"}), _CATALOG)
    assert state["slots"]["grid_resolution"] == "0p25"  # add never clobbers


def test_extracted_removal_edits_shape():
    op = _Op("remove", {"imports": ["GFS"],
                        "basins": [{"basin_name": "Liard", "model_adapter": "raven"}]})
    edits = extracted_removal_edits(op)
    assert {"op": "remove", "target": "GFS", "target_kind": "import"} in edits
    assert {"op": "remove", "target": {"basin_name": "Liard"},
            "target_kind": "basin"} in edits
