"""Parity tests: the Streamlit driver (app/chatter.py) must honour the
intent-disambiguation gate exactly like the CLI driver (chat_step.py).

`app/chatter.py::ChatSession._send_inner` is a second, hand-maintained copy
of the turn pipeline. These tests pin the disambiguation behaviour to it so
the two drivers can't silently drift again: a single-half request ASKS (and
resolves nothing), and the persisted answer commits the intent next turn.

The three LLM seams are stubbed (no Ollama):
  * ``check_ollama_for_model`` → None  (pre-flight passes)
  * ``classify_intent``        → forecasting  (the silent default the gate overrides)
  * ``compose_reply``          → sentinel
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# app/ isn't a package on sys.path by default; add it like web_app.py does.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "app"))

import chatter  # noqa: E402


@pytest.fixture
def session(tmp_path, monkeypatch):
    """A ChatSession with the LLM seams stubbed; returns a fresh session."""
    monkeypatch.setattr(chatter, "check_ollama_for_model", lambda *a, **k: None)
    monkeypatch.setattr(
        chatter, "classify_intent",
        lambda *a, **k: {"intent": "build_forecasting_project", "entities": {}},
    )
    monkeypatch.setattr(chatter, "compose_reply", lambda *a, **k: "STUB-REPLY")
    monkeypatch.setattr(chatter, "get_provider", lambda *a, **k: None)

    # Use tmp_path directly (unique per test) as the session dir: it already
    # exists, and its unique name avoids a cross-test logger-name collision
    # (ChatSession keys its file logger on session_dir.name).
    return chatter.ChatSession(
        project_name="parity",
        session_dir=tmp_path,
        username="tester",
    )


def _pattern_paths(state: dict) -> set[str]:
    return {p["pattern"] for p in state.get("patterns", [])}


def test_imports_only_turn_asks_and_does_not_resolve(session):
    res = session.send("Import NOAA GFS grids for precipitation and temperature.")
    # The deterministic question came back — NOT a composed reply.
    assert res.agent_message != "STUB-REPLY"
    assert "(a)" in res.agent_message and "(b)" in res.agent_message
    assert session.state.get("awaiting_intent_disambiguation") is True
    assert not session.state.get("intent_disambiguated")
    assert _pattern_paths(session.state) == set()  # nothing resolved
    assert session.state["slots"].get("imports") == ["GFS"]


def test_answer_a_commits_data_import_only_and_resolves(session):
    session.send("Import NOAA GFS grids for precipitation and temperature.")
    res = session.send("a")
    assert res.agent_message == "STUB-REPLY"  # Phase 5 reached this turn
    assert session.state["intent"] == "build_data_import_only"
    assert session.state.get("intent_disambiguated") is True
    assert session.state.get("awaiting_intent_disambiguation") is False
    assert "auto/nwp_grid_noaa" in _pattern_paths(session.state)


def test_answer_b_commits_forecasting(session):
    session.send("Import NOAA GFS grids for precipitation and temperature.")
    session.send("b")
    assert session.state["intent"] == "build_forecasting_project"
    assert session.state.get("intent_disambiguated") is True
    assert _pattern_paths(session.state)


def test_explicit_narrowing_phrase_skips_the_gate(session):
    # "no basin model" → forced_intent_override fires AND the gate's
    # narrowing-signal check suppresses the question. Resolves immediately.
    res = session.send("Import NOAA GFS grids, no basin model.")
    assert res.agent_message == "STUB-REPLY"
    assert not session.state.get("awaiting_intent_disambiguation")
    assert session.state["intent"] == "build_data_import_only"
    assert "auto/nwp_grid_noaa" in _pattern_paths(session.state)


def test_forced_override_reaches_the_app(session):
    # The bare forced-override path (no disambiguation involved): an explicit
    # "no basin model" must win over the stubbed classify→forecasting pick.
    session.send("Set up GFS and HRDPS imports and a Raven model for the Liard.")
    # Both halves present → gate silent, forecasting resolves.
    assert session.state["intent"] == "build_forecasting_project"
    res = session.send("Actually, no basin model.")
    assert res.agent_message == "STUB-REPLY"
    assert session.state["intent"] == "build_data_import_only"


def test_unclear_answer_reasks_then_falls_back(session):
    s = session
    s.send("Import NOAA GFS grids for precipitation and temperature.")
    assert s.state.get("intent_disambiguation_asks") == 1
    # A non-answer → gate re-asks (still single-half).
    s.send("hmm, what would you suggest?")
    assert s.state.get("intent_disambiguation_asks") == 2
    assert s.state.get("awaiting_intent_disambiguation") is True
    assert _pattern_paths(s.state) == set()
    # Another non-answer → asks>=2 → forecasting fallback, resolves.
    s.send("not sure")
    assert s.state.get("intent_disambiguated") is True
    assert s.state["intent"] == "build_forecasting_project"
    assert _pattern_paths(s.state)
