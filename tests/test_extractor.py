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

_CATALOG = build_pattern_catalog(Path(__file__).resolve().parents[1] / "fews_agent" / "patterns")


class _Op:
    def __init__(self, action, fields):
        self.action = action
        self.fields = fields


def test_apply_add_merges_and_resolves():
    state = {"slots": {}, "patterns": []}
    note, new = apply_extracted_fields(state, _Op("add", {"imports": ["GFS"]}), _CATALOG)
    assert state["slots"]["imports"] == ["GFS"]
    assert any("auto/gfs/" in p for p in new)
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


def test_remove_data_type_field():
    # Field-level removal: subtract a data_type from the list (the live gap).
    from fews_agent.agent.turn_engine import apply_operation
    state = {"slots": {"imports": ["GFS"],
                       "data_types": ["temperature", "precipitation"]},
             "patterns": [], "intent": "build_data_import_only"}
    reply, _ = apply_operation(
        state, _Op("remove", {"data_types": ["temperature"]}), _CATALOG,
    )
    assert state["slots"]["data_types"] == ["precipitation"]
    assert "temperature" in reply


def test_remove_scalar_field_unsets_it():
    from fews_agent.agent.turn_engine import apply_operation
    state = {"slots": {"imports": ["GFS"], "grid_resolution": "0p50"},
             "patterns": [], "intent": "build_data_import_only"}
    reply, _ = apply_operation(
        state, _Op("remove", {"grid_resolution": "0p50"}), _CATALOG,
    )
    assert "grid_resolution" not in state["slots"]
    assert "grid_resolution" in reply


def test_remove_nothing_recognised():
    from fews_agent.agent.turn_engine import apply_operation
    state = {"slots": {"imports": ["GFS"]}, "patterns": [],
             "intent": "build_data_import_only"}
    reply, _ = apply_operation(state, _Op("remove", {}), _CATALOG)
    assert "Nothing recognised" in reply


# --- confidence signal + confirmation gate --------------------------------

def test_confidence_parsed_and_defaulted():
    assert _run({"action": "add", "fields": {"imports": ["GFS"]},
                 "confidence": 0.3}).confidence == 0.3
    # missing → defaults HIGH (apply as before)
    assert _run({"action": "add", "fields": {"imports": ["GFS"]}}).confidence == 1.0
    # garbage → defaults high
    assert _run({"action": "add", "fields": {"imports": ["GFS"]},
                 "confidence": "abc"}).confidence == 1.0
    # clamped to [0, 1]
    assert _run({"action": "add", "fields": {"imports": ["GFS"]},
                 "confidence": 1.7}).confidence == 1.0
    assert _run({"action": "add", "fields": {"imports": ["GFS"]},
                 "confidence": -2}).confidence == 0.0


def test_needs_confirmation_only_when_effectful_and_uncertain():
    low_effect = _run({"action": "add", "fields": {"imports": ["GFS"]},
                       "confidence": 0.3})
    assert E.needs_confirmation(low_effect) is True
    # high confidence → apply directly
    high = _run({"action": "add", "fields": {"imports": ["GFS"]},
                 "confidence": 0.95})
    assert E.needs_confirmation(high) is False
    # low confidence but NO effect (a question / none) → no confirm needed
    none_op = _run({"action": "none", "fields": {}, "confidence": 0.1})
    assert E.needs_confirmation(none_op) is False
    # low-confidence list → nothing to undo, no confirm
    assert E.needs_confirmation(_run({"action": "list", "confidence": 0.1})) is False


def test_describe_operation_reads_naturally():
    op = _run({"action": "add",
               "fields": {"imports": ["GFS"], "data_types": ["precipitation"]},
               "confidence": 0.3})
    desc = E.describe_operation(op)
    assert "add" in desc and "GFS" in desc and "precipitation" in desc


def test_op_dict_roundtrip():
    op = _run({"action": "set", "fields": {"grid_resolution": "0p50"},
               "confidence": 0.4})
    back = E.op_from_dict(E.op_to_dict(op))
    assert back.action == "set"
    assert back.fields == {"grid_resolution": "0p50"}
    assert back.confidence == 0.4


def test_resolve_pending_operation():
    from fews_agent.agent.turn_engine import resolve_pending_operation as r
    assert r("yes") == "apply"
    assert r("Yes.") == "apply"
    assert r("no") == "discard"
    assert r("cancel") == "discard"
    assert r("add HRDPS instead") is None


# --- unified turn parser (LLM classifies from all 12 intents) -------------

def _parse(payload, focus=None, message="do it"):
    fm = M.get_module(focus) if focus else None
    return E.parse_turn(
        message, focus_module=fm, provider=_Provider(payload),
    )


def test_parse_turn_classifies_a_module_intent():
    p = _parse({"intent": "build_processing", "action": "add",
                "fields": {"imports": ["GFS"]}, "confidence": 0.9})
    assert p.intent == "build_processing"
    assert p.module == "processing"           # derived from the module-intent
    assert p.is_project_intent is False
    assert p.action == "add"
    assert p.fields["imports"] == ["GFS"]


def test_parse_turn_classifies_a_project_intent():
    p = _parse({"intent": "build_data_import_only", "action": "add",
                "fields": {"imports": ["GFS"]}})
    assert p.intent == "build_data_import_only"
    assert p.is_project_intent is True
    assert p.module is None                    # not a module-intent


def test_parse_turn_defaults_to_focus_when_model_silent():
    p = _parse({"intent": None, "action": "add",
                "fields": {"imports": ["HRDPS"]}}, focus="processing")
    assert p.intent == "build_processing"
    assert p.module == "processing"


def test_parse_turn_detects_module_switch():
    p = _parse({"intent": "build_display", "action": "none", "fields": {}},
               focus="processing")
    assert p.module == "display"               # switched away from processing


def test_parse_turn_normalizes_build_synonym_and_validates():
    # 'build_imports' → build_processing; hallucinated import dropped.
    p = _parse({"intent": "build_imports", "action": "add",
                "fields": {"imports": ["GFS", "NOPE"]}})
    assert p.intent == "build_processing"
    assert p.fields["imports"] == ["GFS"]
    assert "import:NOPE" in p.dropped


def test_parse_turn_unknown_intent_with_no_focus_is_none():
    p = _parse({"intent": "build_banana", "action": "none", "fields": {}})
    assert p.intent is None


def test_parse_turn_confidence_and_bad_response():
    assert _parse({"intent": "build_processing", "action": "add",
                   "fields": {"imports": ["GFS"]},
                   "confidence": 0.3}).confidence == 0.3
    # provider error → no-op parse keeping focus's intent
    p = E.parse_turn("x", focus_module=M.get_module("display"),
                     provider=_BoomProvider())
    assert p.action == "none" and p.intent == "build_display"
