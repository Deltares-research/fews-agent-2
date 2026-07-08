"""Tests for the module registry + focus layer (module-mode P1).

Pure functions over the static registry and chat state — no LLM, no build.
"""
from __future__ import annotations

from fews_agent.agent import modules as M
from fews_agent.agent import module_focus as F


# --- registry -------------------------------------------------------------

def test_registry_has_the_nine_agreed_modules():
    keys = [m.key for m in M.list_modules()]
    assert keys == [
        "locations", "parameters", "processing", "display",
        "filters", "topology", "idmap", "system", "root",
    ]


def test_processing_is_the_welded_module():
    proc = M.get_module("processing")
    # The weld: one capability spans ModuleConfig + Workflow (+ ModulePar).
    assert "ModuleConfigFiles/" in proc.folders
    assert "WorkflowFiles/" in proc.folders
    assert "ModuleParFiles/" in proc.folders
    # It claims the three build-capability phases.
    assert set(proc.phases) == {"imports", "process", "model"}
    # Full operation set (you add/remove items here).
    for op in ("add", "set", "remove", "list", "build"):
        assert proc.supports(op)


def test_regionconfig_is_split_not_monolithic():
    # RegionConfigFiles fans out into four independent modules.
    for key in ("locations", "parameters", "filters", "topology"):
        m = M.get_module(key)
        assert any("RegionConfigFiles" in f for f in m.folders), key


def test_normalize_module_synonyms():
    assert M.normalize_module("imports") == "processing"
    assert M.normalize_module("import") == "processing"
    assert M.normalize_module("model") == "processing"
    assert M.normalize_module("spatial") == "display"
    assert M.normalize_module("station") == "locations"
    assert M.normalize_module("timesteps") == "system"
    assert M.normalize_module("frobnicate") is None
    assert M.normalize_module("") is None
    assert M.normalize_module(None) is None


def test_module_for_pattern_folds_capabilities():
    assert M.module_for_pattern("auto/nwp_grid_noaa") == "processing"
    assert M.module_for_pattern("auto/raven_basin") == "processing"
    assert M.module_for_pattern("auto/wf_interpolate_nwp_to_stations") == "processing"
    assert M.module_for_pattern("auto/spatial_display_grid") == "display"


def test_modules_present_orders_by_registry():
    pats = [
        {"pattern": "auto/spatial_display_grid"},
        {"pattern": "auto/nwp_grid_noaa"},
    ]
    # processing precedes display in MODULE_ORDER regardless of input order.
    assert M.modules_present(pats) == ["processing", "display"]


def test_view_only_modules_cannot_add():
    for key in ("filters", "topology", "idmap", "system", "root"):
        m = M.get_module(key)
        assert not m.supports("add"), key
        assert m.supports("build")


# --- focus layer ----------------------------------------------------------

def test_set_focus_records_current_module():
    state: dict = {"slots": {}}
    module, card = F.set_focus(state, "imports")
    assert module is not None and module.key == "processing"
    assert state["current_module"] == "processing"
    assert "Processing" in card


def test_set_focus_unknown_module_does_not_change_state():
    state: dict = {"slots": {}, "current_module": "locations"}
    module, msg = F.set_focus(state, "banana")
    assert module is None
    assert "isn't a module I recognise" in msg
    # focus unchanged on a bad token.
    assert state["current_module"] == "locations"


def test_shared_variables_persist_across_modules_via_slots():
    # geoDatum set while (conceptually) in the locations module...
    state: dict = {"slots": {"geoDatum": "NAD 83"}}
    F.set_focus(state, "locations")
    # ...is inherited by processing without re-asking.
    proc = M.get_module("processing")
    ctx = F.module_shared_context(state, proc)
    assert ctx.get("geoDatum") == "NAD 83"


def test_read_var_falls_back_to_singleton_seed():
    state: dict = {
        "slots": {},
        "singleton_seeds": {"Locations": {"region": "North Sea"}},
    }
    assert F.read_var(state, "region") == "North Sea"
    assert F.read_var(state, "geoDatum") is None


def test_module_slot_status_splits_filled_unfilled():
    state: dict = {"slots": {"imports": ["GFS"]}}
    proc = M.get_module("processing")
    status = F.module_slot_status(state, proc)
    assert "imports" in status["filled"]
    assert "basins" in status["unfilled"]


def test_focus_card_surfaces_inherited_context():
    state: dict = {"slots": {"geoDatum": "WGS 1984", "region": "Caribbean"}}
    proc = M.get_module("processing")
    card = F.focus_card(state, proc)
    assert "Inherited from this session" in card
    assert "geoDatum" in card
    assert "ModuleConfigFiles/" in card


def test_modules_overview_lists_all():
    text = F.modules_overview()
    for m in M.list_modules():
        assert m.key in text


def test_next_unfilled_variable_skips_filled():
    proc = M.get_module("processing")
    # imports filled → the next gap is the first unfilled variable, not imports.
    state = {"slots": {"imports": ["GFS"]}}
    var = F.next_unfilled_variable(state, proc)
    assert var is not None and var != "imports"


def test_next_unfilled_variable_none_when_complete():
    # A module whose every variable is filled returns None.
    params = M.get_module("parameters")  # variables=("data_types",)
    state = {"slots": {"data_types": ["precipitation"]}}
    assert F.next_unfilled_variable(state, params) is None


# --- turn-engine focus scoping --------------------------------------------

def test_module_focus_question_passthrough_without_focus():
    from fews_agent.agent import turn_engine as TE
    state = {"slots": {}}  # no current_module
    q, prompt = TE._module_focus_question(state, None, "FALLBACK-Q")
    assert q == "FALLBACK-Q"
    assert prompt is None


def test_module_focus_question_scopes_to_focused_module():
    from fews_agent.agent import turn_engine as TE
    state = {"slots": {}, "current_module": "processing"}
    q, prompt = TE._module_focus_question(state, None, "FALLBACK-Q")
    # Steers with the module's prompt and asks about the module's own gap,
    # not the generic fallback.
    assert prompt and "Processing" in prompt
    assert q != "FALLBACK-Q"
