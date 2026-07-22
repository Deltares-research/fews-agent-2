"""Slice 1 tests: stepwise per-module build + mid-chat edits.

Covers the deterministic edit/build surface (no LLM, no Ollama):

  * slot mutators (add / remove / set) survive a pattern re-resolve,
  * the slash-edit parser classifies imports vs basins,
  * apply_edit_action mutates slots and re-resolves,
  * build_module renders + XSD-validates a single import instance.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from fews_agent.agent.project_chat import (
    add_module,
    build_pattern_catalog,
    remove_module,
    set_variable,
)
from fews_agent.agent.project_intents import detect_edit_action
from fews_agent.agent import turn_engine
from runners.agent import chat_step
from runners.agent.build_from_blueprint import build_module

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "fews_agent" / "patterns"


@pytest.fixture(scope="module")
def catalog():
    return build_pattern_catalog(PATTERNS_ROOT)


def _import_paths(state):
    return {p["pattern"] for p in state.get("patterns", [])}


def _new_state(intent="build_data_import_only"):
    return {"name": "t", "intent": intent, "slots": {}, "patterns": []}


# --------------------------------------------------------------------------
# Mutators + re-resolve
# --------------------------------------------------------------------------

def test_add_module_resolves_to_pattern(catalog):
    state = _new_state()
    note = add_module(state, "GFS", "import")
    assert "GFS" in note
    chat_step._resolve_patterns(state, catalog)
    assert "auto/nwp_grid_noaa" in _import_paths(state)
    assert state["slots"]["imports"] == ["GFS"]


def test_add_is_deduped(catalog):
    state = _new_state()
    add_module(state, "GFS", "import")
    note = add_module(state, "gfs", "import")  # case-insensitive
    assert "already" in note.lower()
    assert state["slots"]["imports"] == ["GFS"]


def test_remove_survives_reresolve(catalog):
    state = _new_state()
    add_module(state, "GFS", "import")
    add_module(state, "HRDPS", "import")
    chat_step._resolve_patterns(state, catalog)
    assert "auto/nwp_grid_noaa" in _import_paths(state)

    note = remove_module(state, "GFS", "import")
    assert "Removed import GFS" in note
    chat_step._resolve_patterns(state, catalog)
    # A SECOND resolve (simulating a later turn) must not bring GFS back.
    chat_step._resolve_patterns(state, catalog)
    assert "auto/nwp_grid_noaa" not in _import_paths(state)
    assert "auto/nwp_grid_eccc_HRDPS" in _import_paths(state)


def test_remove_absent_is_noop(catalog):
    state = _new_state()
    add_module(state, "HRDPS", "import")
    note = remove_module(state, "GFS", "import")
    assert "not an import" in note


def test_set_grid_resolution_scoped_to_named_import(catalog):
    # Slice 4: /set <import> grid_resolution scopes to that import only.
    state = _new_state()
    add_module(state, "GFS", "import")
    note = set_variable(state, "GFS", "grid_resolution", "0p50")
    assert "GFS only" in note
    assert state["slots"]["import_overrides"]["GFS"]["grid_resolution"] == "0p50"
    assert "grid_resolution" not in state["slots"]  # NOT project-wide
    chat_step._resolve_patterns(state, catalog)
    noaa = [
        p for p in state["patterns"] if p["pattern"] == "auto/nwp_grid_noaa"
    ][0]
    assert noaa["instances"][0].get("grid_resolution") == "0p50"


def test_set_grid_resolution_no_target_is_project_wide(catalog):
    # NL "make it half-degree" (no named import) → project-wide default.
    state = _new_state()
    add_module(state, "GFS", "import")
    note = set_variable(state, "", "grid_resolution", "0p50")
    assert "0p50" in note
    assert state["slots"]["grid_resolution"] == "0p50"
    assert "import_overrides" not in state["slots"]
    chat_step._resolve_patterns(state, catalog)
    noaa = [
        p for p in state["patterns"] if p["pattern"] == "auto/nwp_grid_noaa"
    ][0]
    assert noaa["instances"][0].get("grid_resolution") == "0p50"


def test_per_import_override_beats_project_default(catalog):
    # GFS override (0p25) wins over the project-wide default (0p50).
    state = _new_state()
    add_module(state, "GFS", "import")
    set_variable(state, "", "grid_resolution", "0p50")       # project default
    set_variable(state, "GFS", "grid_resolution", "0p25")    # GFS override
    chat_step._resolve_patterns(state, catalog)
    noaa = [
        p for p in state["patterns"] if p["pattern"] == "auto/nwp_grid_noaa"
    ][0]
    assert noaa["instances"][0].get("grid_resolution") == "0p25"


def test_remove_import_clears_its_override(catalog):
    state = _new_state()
    add_module(state, "GFS", "import")
    set_variable(state, "GFS", "grid_resolution", "0p50")
    assert "GFS" in state["slots"]["import_overrides"]
    remove_module(state, "GFS", "import")
    assert "GFS" not in (state["slots"].get("import_overrides") or {})


def test_set_unknown_variable_is_rejected():
    state = _new_state()
    add_module(state, "GFS", "import")
    note = set_variable(state, "GFS", "bogus_var", "x")
    assert "Settable" in note


def test_set_adapter_scoped_to_basin():
    state = _new_state(intent="build_basin_model_only")
    add_module(state, {"basin_name": "Liard", "model_adapter": "raven"}, "basin")
    note = set_variable(state, "Liard", "model_adapter", "wflow")
    assert "wflow" in note
    assert state["slots"]["basins"][0]["model_adapter"] == "wflow"


# --------------------------------------------------------------------------
# Slash-edit parsing + apply_edit_action
# --------------------------------------------------------------------------

def test_parse_slash_edit_imports():
    edits = chat_step._parse_slash_edit("add", "GFS HRDPS")
    kinds = {e["target_kind"] for e in edits}
    targets = {e["target"] for e in edits}
    assert kinds == {"import"}
    assert targets == {"GFS", "HRDPS"}


def test_parse_slash_edit_basin_with_adapter():
    edits = chat_step._parse_slash_edit("add", "Liard uses raven")
    assert len(edits) == 1
    assert edits[0]["target_kind"] == "basin"
    assert edits[0]["target"]["basin_name"] == "Liard"
    assert edits[0]["target"]["model_adapter"] == "raven"


def test_parse_slash_edit_explicit_basin_prefix():
    edits = chat_step._parse_slash_edit("add", "basin Snare")
    assert edits[0]["target_kind"] == "basin"
    assert edits[0]["target"]["basin_name"] == "Snare"


def test_parse_slash_edit_set():
    edits = chat_step._parse_slash_edit("set", "GFS resolution 0p50")
    assert edits == [{
        "op": "set", "target": "GFS", "target_kind": "variable",
        "variable": "resolution", "value": "0p50",
    }]


def test_apply_edit_action_add_then_remove(catalog):
    state = _new_state()
    note = chat_step.apply_edit_action(
        state, {"op": "add", "target": "GFS", "target_kind": "import"}, catalog
    )
    assert "Added import GFS" in note
    assert "auto/nwp_grid_noaa" in _import_paths(state)

    note = chat_step.apply_edit_action(
        state, {"op": "remove", "target": "GFS", "target_kind": "import"},
        catalog,
    )
    assert "Removed import GFS" in note
    assert "auto/nwp_grid_noaa" not in _import_paths(state)


def test_apply_edit_action_infers_intent_when_missing(catalog):
    state = {"name": "t", "intent": None, "slots": {}, "patterns": []}
    chat_step.apply_edit_action(
        state, {"op": "add", "target": "GFS", "target_kind": "import"}, catalog
    )
    assert state["intent"] is not None
    assert "auto/nwp_grid_noaa" in _import_paths(state)


def test_apply_edit_action_set_normalises_value(catalog):
    state = _new_state()
    add_module(state, "GFS", "import")
    note = chat_step.apply_edit_action(
        state,
        {"op": "set", "target": "GFS", "target_kind": "variable",
         "variable": "resolution", "value": "half-degree"},
        catalog,
    )
    # Named import → per-import override (Slice 4), normalised to the slug.
    assert state["slots"]["import_overrides"]["GFS"]["grid_resolution"] == "0p50"


# --------------------------------------------------------------------------
# build_module integration (renders + XSD-validates one instance)
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def noaa_blueprint(tmp_path_factory):
    """Copy a real GFS-bearing blueprint into an isolated tmp dir."""
    src = (
        REPO_ROOT / "projects" / "viz-demo"
        / "viz-demo_2026-06-16_000000" / "project.yaml"
    )
    dst_dir = tmp_path_factory.mktemp("noaa_bp")
    shutil.copy(src, dst_dir / "project.yaml")
    return dst_dir / "project.yaml"


def test_build_module_single_instance_xsd_ok(noaa_blueprint):
    summary = build_module(
        blueprint_path=noaa_blueprint,
        pattern_root=PATTERNS_ROOT,
        pattern="auto/nwp_grid_noaa",
        instance_match={"nwp_name": "GFS"},
    )
    assert summary["ok"], summary
    assert summary["files_total"] >= 1
    assert summary["files_xsd_ok"] == summary["files_xml"]


def test_build_module_unknown_instance_fails(noaa_blueprint):
    summary = build_module(
        blueprint_path=noaa_blueprint,
        pattern_root=PATTERNS_ROOT,
        pattern="auto/nwp_grid_noaa",
        instance_match={"nwp_name": "NOPE"},
    )
    assert not summary["ok"]
    assert summary["files_total"] == 0


# --------------------------------------------------------------------------
# Slice 2: natural-language edit detection (detect_edit_action)
# --------------------------------------------------------------------------

def test_detect_nl_remove_import():
    edit = detect_edit_action("also drop RDPS")
    assert edit is not None
    assert edit["removed_imports"] == ["RDPS"]
    assert edit["edits"] == [
        {"op": "remove", "target": "RDPS", "target_kind": "import"}
    ]


def test_detect_nl_remove_basin():
    edit = detect_edit_action("remove the Liard basin")
    assert edit is not None
    assert edit["removed_basins"] == ["Liard"]
    assert edit["edits"][0]["target_kind"] == "basin"
    assert edit["edits"][0]["target"]["basin_name"] == "Liard"


def test_detect_nl_set_resolution():
    edit = detect_edit_action("make GFS half-degree")
    assert edit is not None
    sets = [e for e in edit["edits"] if e["op"] == "set"]
    assert sets == [{
        "op": "set", "target": "GFS", "target_kind": "variable",
        "variable": "grid_resolution", "value": "0p50",
    }]


def test_detect_nl_set_horizon():
    edit = detect_edit_action("change the forecast to 7 days")
    assert edit is not None
    sets = [e for e in edit["edits"] if e["op"] == "set"]
    assert len(sets) == 1
    assert sets[0]["variable"] == "forecast_horizon_hours"
    assert sets[0]["value"] == 168


def test_detect_nl_false_positive_guard():
    # A removal cue ("don't want") with no resolvable module must NOT parse.
    assert detect_edit_action("we don't want flooding") is None


def test_detect_nl_first_mention_is_not_an_edit():
    # No change cue — first mention flows through additive slot-fill, not set.
    assert detect_edit_action("import GFS at half-degree resolution") is None


def test_detect_nl_no_edit_verb_returns_none():
    assert detect_edit_action("I'd like a NOAA GFS import please") is None


def _apply_nl_edit(state, message, catalog):
    """Mimic chat_step Phase 2.5: apply NL edits + re-add suppression."""
    facts = turn_engine.filter_prose(message)
    edit = detect_edit_action(message)
    notes = []
    if edit and edit.get("edits"):
        for e in edit["edits"]:
            notes.append(chat_step.apply_edit_action(state, e, catalog))
        ri = {x.lower() for x in edit.get("removed_imports", [])}
        if ri and isinstance(facts.get("imports"), list):
            facts["imports"] = [
                x for x in facts["imports"] if str(x).lower() not in ri
            ]
    # Additive merge (imports only, mirroring the real loop's list union).
    slots = state.setdefault("slots", {})
    for x in facts.get("imports", []):
        imports = slots.setdefault("imports", [])
        if all(str(i).lower() != str(x).lower() for i in imports):
            imports.append(x)
    chat_step._resolve_patterns(state, catalog)
    return notes


def test_nl_remove_survives_readd_suppression(catalog):
    state = _new_state()
    add_module(state, "GFS", "import")
    add_module(state, "RDPS", "import")
    chat_step._resolve_patterns(state, catalog)
    assert "auto/nwp_grid_eccc_RDPS" in _import_paths(state)

    # "drop RDPS" — extract_skills also sees RDPS; suppression must win.
    _apply_nl_edit(state, "please drop RDPS", catalog)
    assert state["slots"]["imports"] == ["GFS"]
    assert "auto/nwp_grid_eccc_RDPS" not in _import_paths(state)
    assert "auto/nwp_grid_noaa" in _import_paths(state)


# --------------------------------------------------------------------------
# Intent override (deterministic, turn-agnostic)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("message,current,expected", [
    # "no basin model" must narrow on turn 1 (current=forecasting). The
    # substring "no model" is NOT inside "no basin model", so this only
    # works because the phrase is listed explicitly.
    ("Configure a NOAA GFS import, no basin model.",
     "build_forecasting_project", "build_data_import_only"),
    ("GFS import, no basin.",
     "build_forecasting_project", "build_data_import_only"),
    # Explicit forecasting request blocks a greedy narrowing match
    # ("no model" inside "no model preference").
    ("I have no model preference yet, full forecasting please.",
     "build_forecasting_project", None),
    # Genuine forecasting prose → no override.
    ("Set up a forecasting project for the Liard basin using raven.",
     None, None),
    ("Model only, no NWP yet.",
     "build_forecasting_project", "build_basin_model_only"),
    # Already the target intent → no-op (None).
    ("no basin model", "build_data_import_only", None),
    # "no forecast" is a narrowing phrase and must NOT be caught by the
    # "forecasting" affirmative guard.
    ("imports only, no forecast workflow",
     "build_forecasting_project", "build_data_import_only"),
])
def test_forced_intent_override(message, current, expected):
    assert turn_engine.forced_intent_override(message, current) == expected


def test_nl_set_overrides_existing_value(catalog):
    state = _new_state()
    add_module(state, "GFS", "import")
    set_variable(state, "GFS", "grid_resolution", "0p25")
    chat_step._resolve_patterns(state, catalog)
    assert state["slots"]["import_overrides"]["GFS"]["grid_resolution"] == "0p25"

    _apply_nl_edit(state, "actually make GFS half-degree", catalog)
    assert state["slots"]["import_overrides"]["GFS"]["grid_resolution"] == "0p50"
    noaa = [
        p for p in state["patterns"] if p["pattern"] == "auto/nwp_grid_noaa"
    ][0]
    assert noaa["instances"][0].get("grid_resolution") == "0p50"
