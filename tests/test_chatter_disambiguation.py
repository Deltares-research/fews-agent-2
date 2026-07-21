"""The Streamlit app is PURE MODULE-MODE — no whole-project intent flow.

The app used to run the intent-disambiguation gate ("imports only or a full
forecasting project?"). That whole-project intent flow was removed: the app now
builds one FEWS-folder module at a time. These tests pin the new contract so it
can't regress back into asking about a project-level intent:

  * a clear catalog request auto-focuses `processing` and resolves — no
    disambiguation question, no LLM needed;
  * the resolver-selecting `intent` is DERIVED from the slots (imports-only →
    build_data_import_only), never a user-facing choice;
  * vague prose asks which module to work on (it does not classify an intent).

The provider is stubbed to explode, proving the common path needs no LLM.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "app"))

import chatter  # noqa: E402


class _Boom:
    def generate_json(self, *a, **k):
        raise AssertionError("pure module-mode should not call the LLM here")


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(chatter, "check_ollama_for_model", lambda *a, **k: None)
    monkeypatch.setattr(chatter, "get_provider", lambda *a, **k: _Boom())
    return chatter.ChatSession(
        project_name="modemode", session_dir=tmp_path, username="tester",
    )


def _pattern_paths(state: dict) -> set[str]:
    return {p["pattern"] for p in state.get("patterns", [])}


def test_single_half_import_auto_focuses_and_resolves(session):
    # No "imports only vs full project?" question — a clear import request just
    # enters the processing module and resolves, deterministically.
    res = session.send("Import GFS grids for precipitation")
    assert res.kind == "edit"
    assert session.state["current_module"] == "processing"
    assert "auto/nwp_grid_noaa" in _pattern_paths(session.state)
    # The applied fact rides in the grey confirmation; a guiding follow-up
    # question in the reply is fine — what must NOT appear is the old
    # "imports only vs full project?" disambiguation gate.
    assert "GFS" in res.confirmation
    reply_low = res.agent_message.lower()
    assert "imports only" not in reply_low and "full project" not in reply_low


def test_intent_is_derived_not_asked(session):
    # The resolver-selecting intent is derived from the slots — imports-only →
    # build_data_import_only (so /done won't demand a basin) — never a choice
    # the user is asked to make.
    session.send("add GFS")
    assert session.state["intent"] == "build_data_import_only"
    session.send("add Liard uses raven")
    assert session.state["intent"] == "build_forecasting_project"


def test_vague_prose_asks_which_module_not_an_intent(session):
    res = session.send("hi, I'd like to build a config")
    assert session.state.get("current_module") is None
    assert "module" in res.agent_message.lower()
    # It does NOT talk about a whole-project intent.
    assert "forecasting project" not in res.agent_message.lower()
