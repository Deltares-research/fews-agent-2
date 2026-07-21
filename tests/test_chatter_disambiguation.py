"""The app never runs a whole-project intent flow — LLM-first contract.

Historically the app ran an intent-disambiguation gate ("imports only or a
full forecasting project?"), then pure module-mode, and now the LLM-first
single-call turn. These tests pin what must NEVER regress:

  * a clear request applies via the model's patch — no disambiguation
    question, no whole-project intent choice shown to the user;
  * the resolver-selecting `intent` is DERIVED from the slots (imports-only →
    build_data_import_only), never asked;
  * the model's reply passes through verbatim — no deterministic gate text is
    injected around it.

The provider is scripted with {reply, patch} payloads (the llm_turn contract).
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


class _Script:
    def __init__(self, *payloads):
        self.payloads = list(payloads)

    def generate_json(self, system, user, schema):
        if not self.payloads:
            raise AssertionError("LLM called more times than scripted")
        return _Resp(self.payloads.pop(0))


def _session(tmp_path, monkeypatch, *payloads):
    script = _Script(*payloads)
    monkeypatch.setattr(chatter, "check_ollama_for_model", lambda *a, **k: None)
    monkeypatch.setattr(chatter, "get_provider", lambda *a, **k: script)
    return chatter.ChatSession(
        project_name="modemode", session_dir=tmp_path, username="tester",
    )


def _pattern_paths(state: dict) -> set[str]:
    return {p["pattern"] for p in state.get("patterns", [])}


def test_import_request_applies_without_a_gate(tmp_path, monkeypatch):
    # No "imports only vs full project?" question — the model's patch applies
    # and its reply passes through untouched.
    s = _session(tmp_path, monkeypatch, {
        "reply": "Added GFS with precipitation. Want a map area for it?",
        "patch": [{"op": "add_import", "name": "GFS",
                   "data_types": ["precipitation"]}],
    })
    res = s.send("Import GFS grids for precipitation")
    assert res.kind == "edit"
    assert "auto/nwp_grid_noaa" in _pattern_paths(s.state)
    assert "GFS" in res.confirmation                     # grey channel
    reply_low = res.agent_message.lower()
    assert "imports only" not in reply_low
    assert "full project" not in reply_low


def test_intent_is_derived_not_asked(tmp_path, monkeypatch):
    # The resolver-selecting intent is derived from the slots — imports-only →
    # build_data_import_only (so /done won't demand a basin) — never a choice
    # the user is asked to make. Driven via the deterministic slash path so
    # this holds independent of any model behaviour.
    s = _session(tmp_path, monkeypatch)
    s.send("/module processing")
    s.send("/add GFS")
    assert s.state["intent"] == "build_data_import_only"
    s.send("/add Liard uses raven")
    assert s.state["intent"] == "build_forecasting_project"


def test_model_reply_passes_through_for_vague_prose(tmp_path, monkeypatch):
    # Vague prose is the MODEL's to handle (empty patch + its own question);
    # nothing is applied and no whole-project intent choice is injected.
    s = _session(tmp_path, monkeypatch, {
        "reply": "Happy to help — what data should this project bring in?",
        "patch": [],
    })
    res = s.send("hi, I'd like to build a config")
    assert res.kind == "reply"
    assert res.confirmation == ""
    assert s.state.get("slots", {}).get("imports") in (None, [])
    assert "forecasting project" not in res.agent_message.lower()
