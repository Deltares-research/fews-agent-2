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
    assert M.module_for_pattern("auto/gfs/deterministic") == "processing"
    assert M.module_for_pattern("auto/basin/raven") == "processing"
    assert M.module_for_pattern("auto/wf_interpolate_nwp_to_stations") == "processing"
    assert M.module_for_pattern("auto/spatial_display_grid") == "display"


def test_modules_present_orders_by_registry():
    pats = [
        {"pattern": "auto/spatial_display_grid"},
        {"pattern": "auto/gfs/deterministic"},
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
    assert "ModuleConfigFiles" in card


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


def test_focus_card_is_a_discrete_grey_status_line():
    state: dict = {"slots": {"geoDatum": "WGS 1984", "region": "Caribbean"}}
    proc = M.get_module("processing")
    card = F.focus_card(state, proc)
    # ONE quiet "Focused on <FEWS folder>." line — labels anchor to the real
    # FEWS folder names (the constant every configurator knows), and the short
    # form drops the parenthetical.
    assert card == "Focused on ModuleConfigFiles + WorkflowFiles."
    # Explicitly NOT the pile the configurator kept rejecting.
    assert "You're now on" not in card
    assert "Carrying over" not in card
    assert "ModuleConfigFiles/" not in card
    assert "Still to set" not in card
    assert "\n" not in card


def test_module_welcome_is_just_the_focused_question():
    from fews_agent.agent import turn_engine as TE
    state: dict = {"slots": {}, "current_module": "processing"}
    proc = M.get_module("processing")
    welcome = TE.module_welcome(state, proc)
    # The main reply is the question — the grey status rides separately.
    assert "?" in welcome
    assert "You're now on" not in welcome
    assert "Carrying over" not in welcome


def test_assembly_generated_modules_never_claim_ready():
    """Regression for the screenshot bug: '/module root' on an EMPTY project
    replied 'This module is ready — want me to build it?' — a template lie
    (RootConfigFiles is generated at final assembly and is not built on its
    own). Entry must say where the files come from, honestly."""
    from fews_agent.agent import turn_engine as TE
    for key in ("root", "filters", "topology", "idmap", "system"):
        mod = M.get_module(key)
        welcome = TE.module_welcome({"slots": {}}, mod)
        low = welcome.lower()
        assert "module is ready" not in low, (key, welcome)
        assert "want me to build" not in low, (key, welcome)
        assert "final assembly" in low, (key, welcome)
    # After a successful assembly the message reflects that instead.
    built = TE.module_welcome({"slots": {}, "full_build_ok": True},
                              M.get_module("root"))
    assert "last assembly" in built.lower()


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


# --- module-mode guiding reply (LLM main voice + grey confirmation) -------

def test_module_progress_splits_done_todo_and_readiness():
    from fews_agent.agent import turn_engine as TE
    proc = M.get_module("processing")
    # An import present → processing is buildable; imports shows under done.
    state = {"slots": {"imports": ["GFS"]}}
    prog = TE._module_progress(state, proc, catalog=None)
    assert prog["ready"] is True
    assert any("GFS" in d for d in prog["done"])
    assert prog["suggested_next"]  # a concrete next step to guide toward
    # Empty processing → not yet buildable.
    empty = TE._module_progress({"slots": {}}, proc, catalog=None)
    assert empty["ready"] is False


def test_compose_module_reply_falls_back_without_provider():
    from fews_agent.agent import turn_engine as TE
    proc = M.get_module("processing")
    state = {"slots": {"imports": ["GFS"]}, "current_module": "processing"}
    # No provider → the focused QUESTION alone (the "what changed" note is shown
    # separately as the grey confirmation, so it must NOT be repeated here —
    # that was the double "Applied: …" bug).
    reply = TE.compose_module_reply(
        state, proc, "Applied: imports=['GFS']", catalog=None, provider=None
    )
    assert "Applied:" not in reply           # the note is NOT in the reply
    assert "?" in reply                      # carries the focused follow-up
    assert "weather variables" in reply      # ...the next-step question


def test_run_module_turn_edit_splits_confirmation_from_reply():
    """An edit's mechanical fact rides in `confirmation` (grey); the guiding
    reply is composed separately (deterministic fallback when the provider
    can't compose)."""
    from fews_agent.agent import turn_engine as TE

    class _FakeProvider:
        # Extracts nothing useful and can't compose → both paths fall back to
        # the deterministic detectors / template.
        def generate_json(self, *a, **k):
            raise RuntimeError("no LLM in this test")

    state = {"slots": {}, "current_module": "processing"}
    catalog = {}
    proc = M.get_module("processing")
    # "add GFS" is caught by the deterministic pre-pass (no LLM needed).
    res = TE.run_module_turn(
        state, "add GFS", catalog, proc, provider=_FakeProvider(),
    )
    assert res.kind == "edit"
    # The mechanical fact is the muted confirmation, not the main reply.
    assert "GFS" in res.confirmation
    assert res.reply  # a guiding reply is present
    assert "GFS" in (state["slots"].get("imports") or [])


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


# --- cold module entry ----------------------------------------------------

def test_cold_entry_fires_on_clear_module_requests():
    assert F.detect_module_entry("let's configure locations") == "locations"
    assert F.detect_module_entry("work on the display") == "display"
    assert F.detect_module_entry("set up filters") == "filters"
    # Rule 1: the literal word "module".
    assert F.detect_module_entry("open the imports module") == "processing"
    assert F.detect_module_entry("the processing module please") == "processing"
    # Rule 3: bare module name.
    assert F.detect_module_entry("filters") == "filters"
    assert F.detect_module_entry("the display") == "display"


def test_cold_entry_does_not_hijack_whole_project_prose():
    # These are the exact shapes the intent-pipeline tests send cold — cold
    # entry MUST fall through (return None) so they still reach the classifier.
    for prose in (
        "Import NOAA GFS grids for precipitation and temperature.",
        "Import NOAA GFS grids, no basin model.",
        "Set up GFS and HRDPS imports and a Raven model for the Liard.",
        "set up an import project",
        "I want a forecasting project for the Liard basin",
    ):
        assert F.detect_module_entry(prose) is None, prose


def test_cold_entry_ignores_generic_import_model_words():
    # "imports"/"model" alone must not enter processing — too collision-prone
    # with whole-project descriptions. Only the explicit "module" word or a
    # distinct-name module does.
    assert F.detect_module_entry("configure the imports and the model") is None


# --- deterministic module switch (safety-net) -----------------------------

def test_switch_fires_on_navigation_to_different_module():
    # From display focus — the exact phrasings the LLM got wrong live.
    for msg in (
        "go back to the processing module",
        "switch to the processing module",
        "switch to processing",
        "let's work on the imports",
        "go back to processing",
        "go to imports",
    ):
        assert F.detect_module_switch(msg, "display") == "processing", msg


def test_switch_none_when_staying_or_same_module():
    # No navigation → None (the op stays in the focused module).
    assert F.detect_module_switch("now visualize the grids", "display") is None
    assert F.detect_module_switch("stay here and add a plot", "display") is None
    assert F.detect_module_switch("add a GFS import", "processing") is None
    # Naming the SAME module is not a switch.
    assert F.detect_module_switch("switch to the display module", "display") is None
    # No focus → no switch.
    assert F.detect_module_switch("switch to processing", None) is None


def test_switch_to_a_distinct_module():
    assert F.detect_module_switch("go to the display", "processing") == "display"
    assert F.detect_module_switch("work on locations now", "processing") == "locations"
