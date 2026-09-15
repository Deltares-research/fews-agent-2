"""Parity tests: module-mode in the Streamlit driver (app/chatter.py).

The CLI (chat_step.py) and the app (ChatSession) must expose the same
module-mode surface: `/modules`, `/module <name>`, and the prose-operation
path that fires when a module is in focus. These drive the real
`ChatSession.send()` so the two turn loops can't drift.

`/modules` and `/module` are deterministic (no LLM). The prose-operation
turn calls the extractor, so its provider is stubbed to return a canned
extraction — no Ollama.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "app"))

import chatter  # noqa: E402


class _Resp:
    def __init__(self, data):
        self.data = data


class _Provider:
    """Provider stub returning a fixed extraction payload."""

    def __init__(self, payload):
        self._payload = payload

    def generate_json(self, system, user, schema):
        return _Resp(self._payload)


class _LLMScript:
    """Scripted {reply, patch} payloads for the LLM-first turn, in order."""

    def __init__(self, *payloads):
        self.payloads = list(payloads)

    def generate_json(self, system, user, schema):
        if not self.payloads:
            raise AssertionError("LLM called more times than scripted")
        return _Resp(self.payloads.pop(0))


def _llm_session(tmp_path, monkeypatch, *payloads):
    """A ChatSession whose prose turns run the LLM-first patch loop with the
    given scripted responses (slash commands never consume one). ONE shared
    script instance — get_provider is called per turn, so the queue must
    persist across calls."""
    script = _LLMScript(*payloads)
    monkeypatch.setattr(chatter, "check_ollama_for_model", lambda *a, **k: None)
    monkeypatch.setattr(chatter, "get_provider", lambda *a, **k: script)
    return chatter.ChatSession(
        project_name="modmode", session_dir=tmp_path, username="tester",
    )


def _session(tmp_path, monkeypatch, payload):
    monkeypatch.setattr(chatter, "check_ollama_for_model", lambda *a, **k: None)
    monkeypatch.setattr(
        chatter, "get_provider", lambda *a, **k: _Provider(payload)
    )
    return chatter.ChatSession(
        project_name="modmode", session_dir=tmp_path, username="tester",
    )


# --- discoverability -------------------------------------------------------

def test_module_mode_commands_are_documented_in_help():
    # If these drop out of /help, module-mode becomes invisible to users
    # even though both drivers support it.
    from fews_agent.agent.project_intents import compose_help_reply
    help_text = compose_help_reply("help")
    assert "/modules" in help_text
    assert "/module <name>" in help_text
    # the natural-language + confirmation affordances are mentioned
    assert "plain language" in help_text.lower()
    assert "confirm" in help_text.lower()


# --- deterministic module commands ----------------------------------------

def test_modules_lists_the_registry(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, {})
    res = s.send("/modules")
    for key in ("locations", "processing", "display", "filters"):
        assert key in res.agent_message


def test_module_focus_selects_and_persists(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, {})
    res = s.send("/module processing")
    # The FEWS folder name rides in the grey confirmation ("Focused on
    # ModuleConfigFiles + WorkflowFiles."); the main reply is the question.
    assert "ModuleConfigFiles" in res.confirmation
    assert "?" in res.agent_message
    assert s.state["current_module"] == "processing"


def test_module_unknown_token_does_not_change_focus(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, {})
    s.send("/module display")
    s.send("/module banana")
    assert s.state["current_module"] == "display"


# --- prose-operation path (extractor) -------------------------------------

def test_prose_add_applies_patch_and_reply_passes_through(tmp_path, monkeypatch):
    # LLM-first: the model's reply IS the reply (with its own follow-up
    # question), and its patch is what gets applied. The grey channel carries
    # the applied facts.
    s = _llm_session(tmp_path, monkeypatch, {
        "reply": "Added GFS. Which weather variables should it carry?",
        "patch": [{"op": "add_import", "name": "GFS"}],
    })
    res = s.send("add a GFS import")
    assert res.kind == "edit"
    assert s.state["slots"]["imports"] == ["GFS"]
    assert "Which weather variables" in res.agent_message   # model's voice
    assert "GFS" in res.confirmation                        # grey channel
    assert "auto/gfs/gribfilter" in {p["pattern"] for p in s.state["patterns"]}
    # /vars (deterministic, no LLM payload consumed) still lists the project.
    assert "Modules in this project" in s.send("/vars").agent_message


def test_slash_commands_never_call_the_llm(tmp_path, monkeypatch):
    # The deterministic bypass lives in the SLASH commands now: with a
    # provider that explodes, /module, /add, /vars all still work.
    class _Boom:
        def generate_json(self, *a, **k):
            raise AssertionError("slash commands must not call the LLM")

    monkeypatch.setattr(chatter, "check_ollama_for_model", lambda *a, **k: None)
    monkeypatch.setattr(chatter, "get_provider", lambda *a, **k: _Boom())
    s = chatter.ChatSession(
        project_name="det", session_dir=tmp_path, username="t",
    )
    s.send("/module processing")
    res = s.send("/add GFS")
    assert res.kind == "edit"
    assert "GFS" in s.state["slots"]["imports"]
    assert "Modules in this project" in s.send("/vars").agent_message


def test_prose_compound_patch_in_one_turn(tmp_path, monkeypatch):
    # The single-call payoff at the app level: one message, several ops.
    s = _llm_session(tmp_path, monkeypatch, {
        "reply": "Added GFS with precipitation and temperature.",
        "patch": [{"op": "add_import", "name": "GFS",
                   "data_types": ["precipitation", "temperature"]}],
    })
    res = s.send("add GFS with precip and temperature")
    assert res.kind == "edit"
    assert set(s.state["slots"]["data_types"]) == {
        "precipitation", "temperature",
    }


def test_prose_hallucinated_import_dropped_loudly(tmp_path, monkeypatch):
    # The trust boundary holds at the app level: a patch op naming something
    # outside the catalog is dropped and surfaced, valid ops still apply.
    s = _llm_session(tmp_path, monkeypatch, {
        "reply": "Added GFS and NOTREAL.",
        "patch": [{"op": "add_import", "name": "GFS"},
                  {"op": "add_import", "name": "NOTREAL"}],
    })
    res = s.send("pull in the usual sources")
    assert res.kind == "edit"
    assert s.state["slots"]["imports"] == ["GFS"]        # NOTREAL dropped
    assert "NOTREAL" in res.agent_message                # surfaced loudly
    assert "Not applied" in res.agent_message


# --- grid coordinates subwindow (/coordinates) -----------------------------

def test_coordinates_with_no_grids_is_a_plain_reply(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, {})
    res = s.send("/coordinates")
    # Nothing to set coordinates for yet → a normal reply, no subwindow.
    assert res.kind == "reply"
    assert res.coordinates_request is None
    # It tells them what to do in PLAIN LANGUAGE — no slash command.
    assert "add one first" in res.agent_message.lower()
    assert "/add" not in res.agent_message


def _gfs_added(tmp_path, monkeypatch):
    """A session with GFS added via one scripted LLM turn."""
    s = _llm_session(tmp_path, monkeypatch, {
        "reply": "Added GFS.",
        "patch": [{"op": "add_import", "name": "GFS"}],
    })
    s.send("add a GFS import")
    return s


def test_coordinates_opens_subwindow_for_resolved_grids(tmp_path, monkeypatch):
    s = _gfs_added(tmp_path, monkeypatch)
    res = s.send("/coordinates")
    # kind="coordinates" signals the web app to open the modal; the payload
    # carries the eligible NWP grids (geometry None until set).
    assert res.kind == "coordinates"
    names = {g["name"] for g in res.coordinates_request}
    assert "GFS" in names
    assert all(g["geometry"] is None for g in res.coordinates_request)


def test_coordinates_via_llm_signal(tmp_path, monkeypatch):
    # Prose route in the LLM-first world: the model emits open_coordinates.
    s = _llm_session(
        tmp_path, monkeypatch,
        {"reply": "Added GFS.",
         "patch": [{"op": "add_import", "name": "GFS"}]},
        {"reply": "Opening the map for GFS.",
         "patch": [{"op": "open_coordinates", "name": "GFS"}]},
    )
    s.send("add GFS")
    res = s.send("i want to set the map area")
    assert res.kind == "coordinates"
    assert {g["name"] for g in res.coordinates_request} == {"GFS"}


def test_coordinates_payload_carries_effective_cell_size(tmp_path, monkeypatch):
    s = _gfs_added(tmp_path, monkeypatch)
    res = s.send("/coordinates")
    gfs = next(g for g in res.coordinates_request if g["name"] == "GFS")
    # Effective cell size drives the live map box; GFS's bundled default is 0.25.
    assert gfs["cell_size"] == 0.25
    # A resolution override changes the effective cell size the map draws with.
    s.state["slots"].setdefault("import_overrides", {}).setdefault(
        "GFS", {})["grid_resolution"] = "0p50"
    res2 = s.send("/coordinates")
    gfs2 = next(g for g in res2.coordinates_request if g["name"] == "GFS")
    assert gfs2["cell_size"] == 0.5


def test_apply_grid_geometry_sets_scoped_override_and_reflows(tmp_path, monkeypatch):
    s = _gfs_added(tmp_path, monkeypatch)
    res = s.apply_grid_geometry(
        "GFS", first_x=-11.75, first_y=8.75, columns=48, rows=30,
    )
    assert res.kind == "edit"
    geom = s.state["slots"]["import_overrides"]["GFS"]["grid_geometry"]
    assert geom == {"first_x": -11.75, "first_y": 8.75,
                    "columns": 48, "rows": 30}
    # It rides onto the resolved instance (→ project.yaml → build rewriter).
    inst = next(
        i for p in s.state["patterns"] if p["pattern"] == "auto/gfs/gribfilter"
        for i in p["instances"]
    )
    assert inst["grid_geometry"] == geom
    # A re-open now prefills the current geometry.
    reopened = s.send("/coordinates GFS")
    gfs = next(g for g in reopened.coordinates_request if g["name"] == "GFS")
    assert gfs["geometry"] == geom


def test_uncertain_model_asks_instead_of_applying(tmp_path, monkeypatch):
    # The confidence gate's successor: when the model is unsure, it asks its
    # own question with an EMPTY patch — a clean reply turn, nothing applied,
    # no pending-op machinery. Confirming is then just the next turn's patch.
    s = _llm_session(
        tmp_path, monkeypatch,
        {"reply": "Did you mean the NOAA GFS global forecast?", "patch": []},
        {"reply": "Added GFS.",
         "patch": [{"op": "add_import", "name": "GFS"}]},
    )
    res = s.send("hmm, maybe that global weather source?")
    assert res.kind == "reply"
    assert not s.state["slots"].get("imports")     # NOT applied
    assert res.confirmation == ""                  # no grey fact
    s.send("yes, that one")
    assert s.state["slots"]["imports"] == ["GFS"]


def test_prose_without_focus_still_applies(tmp_path, monkeypatch):
    # No module focus needed: prose goes straight to the LLM-first turn and
    # the patch applies — there is no whole-project intent pipeline and no
    # cold-entry routing to satisfy first.
    s = _llm_session(tmp_path, monkeypatch, {
        "reply": "Added GFS.",
        "patch": [{"op": "add_import", "name": "GFS"}],
    })
    assert s.state.get("current_module") is None
    res = s.send("set up an import project with GFS")
    assert res.kind == "edit"
    assert s.state["slots"]["imports"] == ["GFS"]
