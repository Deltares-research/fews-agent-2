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


def _session(tmp_path, monkeypatch, payload):
    monkeypatch.setattr(chatter, "check_ollama_for_model", lambda *a, **k: None)
    monkeypatch.setattr(
        chatter, "get_provider", lambda *a, **k: _Provider(payload)
    )
    return chatter.ChatSession(
        project_name="modmode", session_dir=tmp_path, username="tester",
    )


# --- deterministic module commands ----------------------------------------

def test_modules_lists_the_registry(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, {})
    res = s.send("/modules")
    for key in ("locations", "processing", "display", "filters"):
        assert key in res.agent_message


def test_module_focus_selects_and_persists(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, {})
    res = s.send("/module processing")
    assert "Processing" in res.agent_message
    assert s.state["current_module"] == "processing"


def test_module_unknown_token_does_not_change_focus(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, {})
    s.send("/module display")
    s.send("/module banana")
    assert s.state["current_module"] == "display"


# --- prose-operation path (extractor) -------------------------------------

def test_prose_add_applies_and_drops_hallucination(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, {
        "action": "add",
        "fields": {"imports": ["GFS", "NOTREAL"],
                   "data_types": ["precipitation"]},
    })
    s.send("/module processing")
    res = s.send("add a GFS import with precipitation")
    assert res.kind == "edit"
    assert s.state["slots"]["imports"] == ["GFS"]        # NOTREAL dropped
    assert s.state["slots"]["data_types"] == ["precipitation"]
    assert "NOTREAL" in res.agent_message                # surfaced loudly
    assert "auto/nwp_grid_noaa" in {
        p["pattern"] for p in s.state["patterns"]
    }


def test_prose_without_focus_uses_intent_pipeline(tmp_path, monkeypatch):
    # No module in focus → the extractor path must NOT fire; the message
    # goes to the normal pipeline. We assert the extractor didn't apply by
    # checking current_module is unset and the payload wasn't used.
    from fews_agent.agent import turn_engine
    monkeypatch.setattr(
        turn_engine, "classify_intent",
        lambda *a, **k: {"intent": "build_data_import_only", "entities": {}},
    )
    monkeypatch.setattr(turn_engine, "compose_reply", lambda *a, **k: "STUB")
    s = _session(tmp_path, monkeypatch, {"action": "add",
                                         "fields": {"imports": ["GFS"]}})
    assert s.state.get("current_module") is None
    res = s.send("set up an import project")
    assert res.agent_message == "STUB"                    # pipeline reply, not extractor
