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
    assert "Processing" in res.agent_message
    assert s.state["current_module"] == "processing"


def test_module_unknown_token_does_not_change_focus(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, {})
    s.send("/module display")
    s.send("/module banana")
    assert s.state["current_module"] == "display"


# --- prose-operation path (extractor) -------------------------------------

def test_reply_guides_with_a_next_step(tmp_path, monkeypatch):
    # After adding an import, the agent proactively suggests what to do next
    # (choose variables / coordinates / build) instead of only confirming.
    s = _session(tmp_path, monkeypatch, {
        "action": "add", "fields": {"imports": ["GFS"]},
    })
    s.send("/module processing")
    res = s.send("add a GFS import")
    # After adding an import it ASKS the one focused next question (weather
    # variables), rather than dumping the full list + a command menu.
    assert "weather variables" in res.agent_message.lower()
    assert "GFS" in res.agent_message
    assert "Modules in this project" not in res.agent_message   # no pile-dump
    # /list is where the full listing lives (and it still guides).
    listing = s.send("/list").agent_message
    assert "Modules in this project" in listing
    # The /add slash command (deterministic edit path) also asks a question.
    assert "?" in s.send("/add HRDPS").agent_message


def test_deterministic_prose_add_needs_no_llm(tmp_path, monkeypatch):
    # "add GFS and HRDPS" is known structure (verb + catalog entities) → parsed
    # deterministically; the provider (which would blow up) is never called.
    class _Boom:
        def generate_json(self, *a, **k):
            raise AssertionError("LLM extractor should not be called")

    monkeypatch.setattr(chatter, "check_ollama_for_model", lambda *a, **k: None)
    monkeypatch.setattr(chatter, "get_provider", lambda *a, **k: _Boom())
    s = chatter.ChatSession(
        project_name="det", session_dir=tmp_path, username="t",
    )
    s.send("/module processing")
    res = s.send("add GFS and HRDPS")
    assert res.kind == "edit"
    assert set(s.state["slots"]["imports"]) == {"GFS", "HRDPS"}
    assert "auto/nwp_grid_noaa" in {p["pattern"] for p in s.state["patterns"]}


def test_prose_sets_weather_variables_no_llm(tmp_path, monkeypatch):
    # "we will use precipitation" is known structure too → deterministic; the
    # provider is never called. This is the gap the /coordinates-era testing
    # surfaced: the hint says to set variables, so prose must set them.
    class _Boom:
        def generate_json(self, *a, **k):
            raise AssertionError("LLM extractor should not be called")

    monkeypatch.setattr(chatter, "check_ollama_for_model", lambda *a, **k: None)
    monkeypatch.setattr(chatter, "get_provider", lambda *a, **k: _Boom())
    s = chatter.ChatSession(
        project_name="dt", session_dir=tmp_path, username="t",
    )
    s.send("/module processing")
    s.send("add GFS")
    res = s.send("we will use precipitation and temperature")
    assert res.kind == "edit"
    assert set(s.state["slots"]["data_types"]) == {"precipitation", "temperature"}


def test_prose_add_via_llm_drops_hallucination(tmp_path, monkeypatch):
    # A FUZZY phrase (no literal catalog token) bypasses the deterministic
    # pre-pass and reaches the LLM parser, whose output is catalog-validated:
    # a hallucinated import is dropped and surfaced loudly.
    s = _session(tmp_path, monkeypatch, {
        "action": "add",
        "fields": {"imports": ["GFS", "NOTREAL"],
                   "data_types": ["precipitation"]},
    })
    s.send("/module processing")
    res = s.send("pull in the usual american forecast source")
    assert res.kind == "edit"
    assert s.state["slots"]["imports"] == ["GFS"]        # NOTREAL dropped
    assert s.state["slots"]["data_types"] == ["precipitation"]
    assert "NOTREAL" in res.agent_message                # surfaced loudly
    assert "auto/nwp_grid_noaa" in {
        p["pattern"] for p in s.state["patterns"]
    }


# --- grid coordinates subwindow (/coordinates) -----------------------------

def test_coordinates_with_no_grids_is_a_plain_reply(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, {})
    res = s.send("/coordinates")
    # Nothing to set coordinates for yet → a normal reply, no subwindow.
    assert res.kind == "reply"
    assert res.coordinates_request is None
    assert "Add one first" in res.agent_message


def test_coordinates_opens_subwindow_for_resolved_grids(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, {
        "action": "add", "fields": {"imports": ["GFS"]},
    })
    s.send("/module processing")
    s.send("add a GFS import")
    res = s.send("/coordinates")
    # kind="coordinates" signals the web app to open the modal; the payload
    # carries the eligible NWP grids (geometry None until set).
    assert res.kind == "coordinates"
    names = {g["name"] for g in res.coordinates_request}
    assert "GFS" in names
    assert all(g["geometry"] is None for g in res.coordinates_request)


def test_coordinates_payload_carries_effective_cell_size(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, {
        "action": "add", "fields": {"imports": ["GFS"]},
    })
    s.send("/module processing")
    s.send("add a GFS import")
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
    s = _session(tmp_path, monkeypatch, {
        "action": "add", "fields": {"imports": ["GFS"]},
    })
    s.send("/module processing")
    s.send("add a GFS import")
    res = s.apply_grid_geometry(
        "GFS", first_x=-11.75, first_y=8.75, columns=48, rows=30,
    )
    assert res.kind == "edit"
    geom = s.state["slots"]["import_overrides"]["GFS"]["grid_geometry"]
    assert geom == {"first_x": -11.75, "first_y": 8.75,
                    "columns": 48, "rows": 30}
    # It rides onto the resolved instance (→ project.yaml → build rewriter).
    inst = next(
        i for p in s.state["patterns"] if p["pattern"] == "auto/nwp_grid_noaa"
        for i in p["instances"]
    )
    assert inst["grid_geometry"] == geom
    # A re-open now prefills the current geometry.
    reopened = s.send("/coordinates GFS")
    gfs = next(g for g in reopened.coordinates_request if g["name"] == "GFS")
    assert gfs["geometry"] == geom


def test_low_confidence_add_asks_before_applying(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, {
        "action": "add", "fields": {"imports": ["GFS"]}, "confidence": 0.3,
    })
    s.send("/module processing")
    # Fuzzy phrase (no literal catalog token) → deterministic pass defers, the
    # LLM parser's low confidence triggers the confirm gate.
    res = s.send("hmm, maybe that global weather source?")
    assert "confirm" in res.agent_message.lower()
    assert s.state.get("_pending_operation") is not None
    assert not s.state["slots"].get("imports")     # NOT applied yet
    # confirming applies it (the 'yes' is intercepted before re-extraction)
    s.send("yes")
    assert s.state["slots"]["imports"] == ["GFS"]
    assert s.state.get("_pending_operation") is None


def test_low_confidence_add_can_be_declined(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, {
        "action": "add", "fields": {"imports": ["GFS"]}, "confidence": 0.2,
    })
    s.send("/module processing")
    s.send("uh, gfs?")
    res = s.send("no")
    assert "cancel" in res.agent_message.lower()
    assert not s.state["slots"].get("imports")
    assert s.state.get("_pending_operation") is None


def test_prose_without_focus_is_pure_module_mode(tmp_path, monkeypatch):
    # Pure module-mode: with no module in focus, a clear catalog request
    # auto-focuses `processing` and applies — it does NOT run a whole-project
    # intent pipeline. (The LLM stub would raise if reached.)
    s = _session(tmp_path, monkeypatch, {})
    assert s.state.get("current_module") is None
    res = s.send("set up an import project with GFS")
    assert res.kind == "edit"
    assert s.state["current_module"] == "processing"
    assert s.state["slots"]["imports"] == ["GFS"]
