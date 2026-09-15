"""Parity tests: the stepwise edit/list surface in the Streamlit driver.

`app/chatter.py::ChatSession` must expose the same mid-chat edit surface as
the CLI (chat_step.py): slash `/add` `/remove` `/set` `/list` `/phases`, and
natural-language edits ("also add HRDPS", "drop RDPS"). These tests drive the
real `ChatSession.send()` so the two hand-maintained turn loops can't drift.

The slash edits are deterministic (no LLM) and return before the pre-flight
LLM check, so they need no Ollama. The NL-edit turns run the full pipeline,
so the three LLM seams are stubbed (same as test_chatter_disambiguation.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "app"))

import chatter  # noqa: E402

from fews_agent.agent import turn_engine  # noqa: E402


@pytest.fixture
def session(tmp_path, monkeypatch):
    # classify/compose seams live on turn_engine (the shared pipeline);
    # pre-flight + provider resolution stay on the chatter driver.
    monkeypatch.setattr(chatter, "check_ollama_for_model", lambda *a, **k: None)
    monkeypatch.setattr(
        turn_engine, "classify_intent",
        lambda *a, **k: {"intent": "build_forecasting_project", "entities": {}},
    )
    monkeypatch.setattr(turn_engine, "compose_reply", lambda *a, **k: "STUB-REPLY")
    monkeypatch.setattr(chatter, "get_provider", lambda *a, **k: None)
    return chatter.ChatSession(
        project_name="parity", session_dir=tmp_path, username="tester",
    )


def _pattern_paths(state: dict) -> set[str]:
    return {p["pattern"] for p in state.get("patterns", [])}


def _noaa_instance(state: dict) -> dict:
    noaa = [p for p in state["patterns"]
            if p["pattern"] == "auto/gfs/gribfilter"]
    return noaa[0]["instances"][0] if noaa else {}


# --- discoverability: the stepwise commands must show in /help -----------

def test_stepwise_commands_are_documented_in_help():
    # The bare `/help` topic list is the canonical command catalogue (shared
    # by both drivers). If these drop out, the features become invisible to
    # users even though the engine still supports them.
    from fews_agent.agent.project_intents import compose_help_reply
    help_text = compose_help_reply("help")
    # `/vars` subsumes the old `/list` (bare = the instance overview, `/vars
    # GFS` = that instance's tunable variables); list/show remain aliases.
    for cmd in ("/vars", "/phases", "/add", "/remove", "/set", "/build"):
        assert cmd in help_text, f"{cmd} missing from /help"
    # The old name must still be discoverable as an alias, so muscle memory
    # (and older docs) keep working.
    assert "list" in help_text


# --- slash edits (deterministic, no LLM) ---------------------------------

def test_slash_add_resolves_import(session):
    res = session.send("/add GFS")
    assert res.kind == "edit"
    assert "auto/gfs/gribfilter" in _pattern_paths(session.state)
    assert "GFS" in session.state["slots"].get("imports", [])
    # The reply echoes the module list so the user sees current state.
    assert "GFS" in res.agent_message


def test_slash_remove_survives_reresolve(session):
    session.send("/add GFS")
    session.send("/add HRDPS")
    assert "auto/gfs/gribfilter" in _pattern_paths(session.state)
    session.send("/remove GFS")
    # A later /list re-resolves; GFS must not come back.
    session.send("/list")
    assert "auto/gfs/gribfilter" not in _pattern_paths(session.state)
    assert "auto/eccc/HRDPS" in _pattern_paths(session.state)


def test_slash_drop_is_remove(session):
    session.send("/add GFS")
    session.send("/drop GFS")
    assert "GFS" not in session.state["slots"].get("imports", [])


def test_slash_set_horizon_scoped_to_import(session):
    session.send("/add GFS")
    res = session.send("/set GFS horizon 7-day")
    assert res.kind == "edit"
    assert (
        session.state["slots"]["import_overrides"]["GFS"]["forecast_horizon_hours"]
        == 168
    )
    assert _noaa_instance(session.state).get("forecast_horizon_hours") == 168


def test_slash_set_unknown_variable_is_rejected(session):
    session.send("/add GFS")
    res = session.send("/set GFS bogus x")
    assert "recognise" in res.agent_message.lower() or "settable" in res.agent_message.lower()


def test_slash_list_and_phases_are_readonly(session):
    session.send("/add GFS")
    res_list = session.send("/list")
    assert res_list.kind == "reply"
    assert "GFS" in res_list.agent_message
    res_phases = session.send("/phases")
    assert res_phases.kind == "reply"
    # Listing didn't mutate the project.
    assert "GFS" in session.state["slots"].get("imports", [])


# --- natural-language edits (full pipeline; LLM stubbed) -----------------

class _PatchScript:
    """Scripted {reply, patch} payloads for the LLM-first prose turns."""

    def __init__(self, *payloads):
        self.payloads = list(payloads)

    def generate_json(self, system, user, schema):
        class _R:
            def __init__(self, data):
                self.data = data
        if not self.payloads:
            raise AssertionError("LLM called more times than scripted")
        return _R(self.payloads.pop(0))


def test_nl_edit_adds_a_second_import(session, monkeypatch):
    script = _PatchScript(
        {"reply": "Added GFS.",
         "patch": [{"op": "add_import", "name": "GFS"}]},
        {"reply": "Added HRDPS too.",
         "patch": [{"op": "add_import", "name": "HRDPS"}]},
    )
    monkeypatch.setattr(chatter, "get_provider", lambda *a, **k: script)
    session.send("Import NOAA GFS grids, no basin model.")
    assert "GFS" in session.state["slots"].get("imports", [])
    session.send("Also add an HRDPS import.")
    assert "HRDPS" in session.state["slots"].get("imports", [])


def test_nl_edit_removes_an_import(session, monkeypatch):
    script = _PatchScript(
        {"reply": "Added GFS and HRDPS.",
         "patch": [{"op": "add_import", "name": "GFS"},
                   {"op": "add_import", "name": "HRDPS"}]},
        {"reply": "Dropped HRDPS.",
         "patch": [{"op": "remove", "target": "HRDPS"}]},
    )
    monkeypatch.setattr(chatter, "get_provider", lambda *a, **k: script)
    session.send("Import GFS and HRDPS grids, no basin model.")
    assert "HRDPS" in session.state["slots"].get("imports", [])
    session.send("Actually, drop HRDPS.")
    assert "HRDPS" not in session.state["slots"].get("imports", [])
    assert "GFS" in session.state["slots"].get("imports", [])


def test_descriptive_prose_is_not_an_edit(session):
    # "we don't want flooding" must NOT parse as a remove. Verb-gated
    # detection guards this; the slot set stays untouched by any edit.
    session.send("Import NOAA GFS grids, no basin model.")
    before = list(session.state["slots"].get("imports", []))
    session.send("We don't want to miss any flooding events.")
    assert session.state["slots"].get("imports", []) == before


# --- per-phase / per-module build (invokes the real build pipeline) ------

def test_slash_build_phase_returns_validation_summary(session):
    session.send("/add GFS")
    res = session.send("/build imports")
    assert res.kind == "build"
    assert res.project_yaml_path is not None
    assert res.validation_summary is not None
    assert res.validation_summary.get("ok") is True
    assert "imports" in session.state.get("built_phases", [])


def test_slash_build_module_returns_validation_summary(session):
    session.send("/add GFS")
    res = session.send("/build GFS")
    assert res.kind == "build"
    assert res.validation_summary is not None
    assert res.validation_summary.get("ok") is True
    assert "auto/gfs/gribfilter::GFS" in session.state.get("built_modules", [])


def test_build_unknown_module_is_a_plain_note(session):
    session.send("/add GFS")
    res = session.send("/build Nonexistent")
    assert res.kind == "reply"  # no build attempted
    assert res.validation_summary is None
    assert "Nonexistent" in res.agent_message
