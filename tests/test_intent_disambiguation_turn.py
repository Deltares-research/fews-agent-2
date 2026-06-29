"""Slice 2 tests: ask-on-ambiguity wiring in the chat turn loop.

These drive the real ``chat_step.main()`` turn loop end-to-end with the
two LLM calls (``classify_intent``, ``compose_reply``) stubbed out, so no
Ollama is needed. They prove the deterministic gate behaviour that the
pure-helper tests (``test_intent_disambiguation.py``) can't:

  * a single-half request ASKS and does NOT resolve patterns,
  * the persisted answer ('a' / 'b' / a phrasing) commits the intent and
    resolves on the next turn,
  * an explicit narrowing/forecasting signal skips the gate entirely,
  * an unanswered re-ask is capped, then falls back to forecasting.

The stub for ``classify_intent`` deliberately returns
``build_forecasting_project`` — the LLM's default-to-forecasting pick —
so the tests confirm the gate overrides exactly that silent default.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from fews_agent.agent import turn_engine
from runners.agent import chat_step


# --------------------------------------------------------------------------
# Harness: run one turn through the real main() with the LLM stubbed.
# --------------------------------------------------------------------------

@pytest.fixture
def run_turn(tmp_path, monkeypatch):
    """Return a ``run(message) -> state`` driver for a temp project.

    Points ``OUTPUT_ROOT`` at a tmp dir and stubs both LLM calls so the
    turn loop runs offline. Returns the persisted ``.chat_state.json``
    after each turn so tests can assert on intent / patterns / flags.
    """
    monkeypatch.setattr(chat_step, "OUTPUT_ROOT", tmp_path)

    # The Phase 1–5 pipeline lives in turn_engine and calls classify_intent /
    # compose_reply from ITS namespace, so the LLM seams are patched there
    # (one seam for both drivers). OUTPUT_ROOT is driver state and stays on
    # chat_step.
    # classify_intent: emulate the LLM's default-to-forecasting pick. The
    # gate exists precisely to override this silent default, so returning
    # it here is the adversarial case.
    monkeypatch.setattr(
        turn_engine, "classify_intent",
        lambda *a, **k: {"intent": "build_forecasting_project", "entities": {}},
    )
    # compose_reply: a sentinel so a test can tell Phase 5 was reached
    # (i.e. the gate did NOT short-circuit this turn).
    monkeypatch.setattr(
        turn_engine, "compose_reply", lambda *a, **k: "STUB-REPLY",
    )

    project_name = "disambig-it"

    def run(message: str) -> dict:
        rc = chat_step.main(["--project-name", project_name, "--message", message])
        assert rc == 0
        # Resolve the (single) instance dir under OUTPUT_ROOT/project_name.
        parent = tmp_path / project_name
        inst = sorted(d for d in parent.iterdir() if d.is_dir())[-1]
        return json.loads((inst / ".chat_state.json").read_text(encoding="utf-8"))

    return run


def _pattern_paths(state: dict) -> set[str]:
    return {p["pattern"] for p in state.get("patterns", [])}


# --------------------------------------------------------------------------
# Turn 1: the gate fires on a single-half request.
# --------------------------------------------------------------------------

def test_imports_only_turn_asks_and_does_not_resolve(run_turn):
    state = run_turn("Import NOAA GFS grids for precipitation and temperature.")
    # The gate short-circuited BEFORE Phase 4 resolve.
    assert state.get("awaiting_intent_disambiguation") is True
    assert not state.get("intent_disambiguated")
    assert state.get("intent_disambiguation_which") == "imports"
    assert _pattern_paths(state) == set()  # nothing resolved yet
    # ...but the half it described is recorded in slots.
    assert state["slots"].get("imports") == ["GFS"]


def test_basin_only_turn_asks(run_turn):
    state = run_turn("Set up a Raven model for the Liard.")
    assert state.get("awaiting_intent_disambiguation") is True
    assert state.get("intent_disambiguation_which") == "basin"
    assert _pattern_paths(state) == set()


# --------------------------------------------------------------------------
# Turn 2: the persisted answer commits the intent and resolves.
# --------------------------------------------------------------------------

def test_answer_a_commits_data_import_only_and_resolves(run_turn):
    run_turn("Import NOAA GFS grids for precipitation and temperature.")
    state = run_turn("a")
    assert state["intent"] == "build_data_import_only"
    assert state.get("intent_disambiguated") is True
    assert state.get("awaiting_intent_disambiguation") is False
    # Patterns now resolve from the GFS slot under the chosen intent.
    assert "auto/nwp_grid_noaa" in _pattern_paths(state)


def test_answer_b_commits_forecasting_and_resolves(run_turn):
    run_turn("Import NOAA GFS grids for precipitation and temperature.")
    state = run_turn("b")
    assert state["intent"] == "build_forecasting_project"
    assert state.get("intent_disambiguated") is True
    assert _pattern_paths(state)  # forecasting resolves a (larger) pattern set


def test_answer_full_project_phrasing_commits_forecasting(run_turn):
    run_turn("Import NOAA GFS grids for precipitation and temperature.")
    state = run_turn("the full project please")
    assert state["intent"] == "build_forecasting_project"
    assert state.get("intent_disambiguated") is True


def test_answer_imports_only_phrasing_commits_data_import(run_turn):
    run_turn("Import NOAA GFS grids for precipitation and temperature.")
    state = run_turn("imports only")
    assert state["intent"] == "build_data_import_only"
    assert "auto/nwp_grid_noaa" in _pattern_paths(state)


# --------------------------------------------------------------------------
# The gate is skipped when the prose is already unambiguous.
# --------------------------------------------------------------------------

def test_explicit_narrowing_phrase_skips_the_gate(run_turn):
    # "no basin model" → forced_intent_override fires AND the gate's
    # narrowing-signal check suppresses the question. Resolves immediately.
    state = run_turn("Import NOAA GFS grids, no basin model.")
    assert not state.get("awaiting_intent_disambiguation")
    assert state["intent"] == "build_data_import_only"
    assert "auto/nwp_grid_noaa" in _pattern_paths(state)


def test_explicit_forecasting_phrase_skips_the_gate(run_turn):
    state = run_turn("Build a full forecasting project, starting with a GFS import.")
    assert not state.get("awaiting_intent_disambiguation")
    assert state["intent"] == "build_forecasting_project"
    assert _pattern_paths(state)


# --------------------------------------------------------------------------
# Unanswered re-asks are capped, then fall back to forecasting.
# --------------------------------------------------------------------------

def test_unclear_answer_reasks_then_falls_back_to_forecasting(run_turn):
    # Turn 1 asks.
    s1 = run_turn("Import NOAA GFS grids for precipitation and temperature.")
    assert s1.get("intent_disambiguation_asks") == 1
    assert s1.get("awaiting_intent_disambiguation") is True

    # Turn 2: a non-answer. The top handler can't parse it, falls through,
    # and the gate re-asks (still a single-half request).
    s2 = run_turn("hmm, what do you recommend?")
    assert s2.get("intent_disambiguation_asks") == 2
    assert s2.get("awaiting_intent_disambiguation") is True
    assert _pattern_paths(s2) == set()  # still not resolved

    # Turn 3: another non-answer. asks >= 2 → forecasting fallback, resolves.
    s3 = run_turn("not sure")
    assert s3.get("intent_disambiguated") is True
    assert s3["intent"] == "build_forecasting_project"
    assert _pattern_paths(s3)  # resolved under the fallback intent
