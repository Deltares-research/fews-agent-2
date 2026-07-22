"""Fixes driven by the 2026-07-22 human test transcripts.

B1 — the agent must never CLAIM a change it didn't apply: when ops drop, the
draft reply (written assuming success) is rewritten by a repair call, or
replaced by a deterministic honest sentence when that call fails.

B2 — ``set_variables`` is catalog-driven: any variable the target's pattern
declares (exactly what the /vars table shows, e.g. ``contribute_parameters``)
is settable/clearable, and the resolver stamps it onto the instance.

Plus: a sidebar module click reads as natural language in history, not
"/module processing".
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fews_agent.agent import turn_engine as TE
from fews_agent.agent.llm_turn import run_llm_turn
from fews_agent.agent.patch_ops import apply_patch
from fews_agent.agent.project_chat import build_pattern_catalog

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalog():
    return build_pattern_catalog(REPO / "fews_agent" / "patterns")


@pytest.fixture()
def state(catalog):
    st = {"slots": {"imports": ["GFS"]},
          "intent": "build_data_import_only"}
    TE.resolve_patterns(st, catalog)
    return st


class _Resp:
    def __init__(self, data):
        self.data = data


class _Scripted:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []

    def generate_json(self, system, user, schema):
        self.calls.append({"system": system, "user": user})
        if not self.payloads:
            raise RuntimeError("script exhausted")
        return _Resp(self.payloads.pop(0))


# --- B2: catalog-driven set_variables --------------------------------------

def test_declared_variable_is_settable(state, catalog):
    """The human-test failure verbatim: the /vars table lists
    contribute_parameters, so set_variables must accept it."""
    res = apply_patch(state, [{"op": "set_variables", "target": "GFS",
                               "values": {"contribute_parameters": "yes"}}],
                      catalog)
    assert res.dropped == []
    assert any("contribute_parameters" in n for n in res.notes)
    ov = state["slots"]["import_overrides"]["GFS"]
    assert ov["contribute_parameters"] is True     # coerced to the bool type


def test_declared_variable_reaches_the_instance(state, catalog):
    apply_patch(state, [{"op": "set_variables", "target": "GFS",
                         "values": {"contribute_parameters": True}}], catalog)
    inst = next(
        i for p in state["patterns"] if p["pattern"] == "auto/nwp_grid_noaa"
        for i in p["instances"] if i.get("nwp_name") == "GFS"
    )
    assert inst["contribute_parameters"] is True


def test_declared_variable_bad_value_dropped(state, catalog):
    res = apply_patch(state, [{"op": "set_variables", "target": "GFS",
                               "values": {"contribute_parameters": "maybe"}}],
                      catalog)
    assert res.notes == []
    assert any("couldn't parse" in d for d in res.dropped)


def test_truly_unknown_variable_still_drops_with_hint(state, catalog):
    res = apply_patch(state, [{"op": "set_variables", "target": "GFS",
                               "values": {"warp_factor": 9}}], catalog)
    assert any("unknown variable" in d for d in res.dropped)
    assert any("contribute_parameters" in d for d in res.dropped)  # the hint


def test_declared_variable_clears_back_to_default(state, catalog):
    apply_patch(state, [{"op": "set_variables", "target": "GFS",
                         "values": {"contribute_parameters": "yes"}}], catalog)
    res = apply_patch(state, [{"op": "remove", "target": "GFS",
                               "variable": "contribute_parameters"}], catalog)
    assert res.dropped == []
    assert "contribute_parameters" not in (
        state["slots"]["import_overrides"].get("GFS") or {})


# --- B1: no fabricated success when ops drop -------------------------------

def test_dropped_ops_trigger_reply_repair(state, catalog):
    """First call returns a success-claiming reply over a bogus op; the
    repair call rewrites it. The shipped reply is the repaired one."""
    prov = _Scripted(
        {"reply": "Set GFS to keep its parameters separate.",   # the lie
         "patch": [{"op": "set_variables", "target": "GFS",
                    "values": {"warp_factor": 9}}]},
        {"reply": "I couldn't change warp_factor — GFS doesn't have that "
                  "setting."},                                  # the repair
    )
    res = run_llm_turn(state, "warp_factor set to 9", catalog, provider=prov)
    assert len(prov.calls) == 2
    assert "keep its parameters separate" not in res.reply      # lie gone
    assert "couldn't change warp_factor" in res.reply
    assert "Not applied" in res.reply                           # loud detail
    # The repair prompt carried the ground truth.
    assert "warp_factor" in prov.calls[1]["user"]
    assert "may wrongly claim success" in prov.calls[1]["user"]


def test_repair_failure_falls_back_to_honest_deterministic(state, catalog):
    prov = _Scripted(
        {"reply": "Removed precipitation from GFS.",            # the lie
         "patch": [{"op": "remove", "target": "precipitation_x"}]},
        # script exhausted → repair call raises → deterministic fallback
    )
    res = run_llm_turn(state, "remove precipitation", catalog, provider=prov)
    assert "Removed precipitation from GFS." not in res.reply
    assert "couldn't apply" in res.reply
    assert "Not applied" in res.reply


def test_clean_patch_never_pays_the_repair_call(state, catalog):
    prov = _Scripted({"reply": "Added HRDPS.",
                      "patch": [{"op": "add_import", "name": "HRDPS"}]})
    res = run_llm_turn(state, "add hrdps", catalog, provider=prov)
    assert len(prov.calls) == 1
    assert res.reply.startswith("Added HRDPS.")


# --- sidebar click = natural-language turn ---------------------------------

def test_focus_module_records_natural_language(tmp_path, monkeypatch):
    from app import chatter as C
    monkeypatch.setattr(C, "check_ollama_for_model", lambda *a, **k: None)
    monkeypatch.setattr(C, "get_provider", lambda *a, **k: object())
    s = C.ChatSession(project_name="click", session_dir=tmp_path, username="t")
    res = s.focus_module("processing")
    user_msgs = [h["message"] for h in s.history if h["role"] == "user"]
    assert user_msgs[-1] == "Let's build ModuleConfigFiles + WorkflowFiles!"
    assert "/module" not in user_msgs[-1]
    assert s.state["current_module"] == "processing"
    assert res.kind == "reply" and res.agent_message


# --- prose undo -------------------------------------------------------------

def test_prose_undo_rolls_back_previous_turn(tmp_path, monkeypatch):
    from app import chatter as C
    monkeypatch.setattr(C, "check_ollama_for_model", lambda *a, **k: None)
    payloads = [
        {"reply": "Added GFS.", "patch": [{"op": "add_import", "name": "GFS"}]},
        {"reply": "Added HRDPS.",
         "patch": [{"op": "add_import", "name": "HRDPS"}]},
        {"reply": "Undone - HRDPS is out again.", "patch": [{"op": "undo"}]},
    ]

    class _Prov:
        def generate_json(self, system, user, schema):
            return _Resp(payloads.pop(0))

    monkeypatch.setattr(C, "get_provider", lambda *a, **k: _Prov())
    s = C.ChatSession(project_name="undodemo", session_dir=tmp_path,
                      username="t")
    s.send("add GFS")
    s.send("add HRDPS")
    assert s.state["slots"]["imports"] == ["GFS", "HRDPS"]
    res = s.send("hmm, undo that")
    assert s.state["slots"]["imports"] == ["GFS"]      # HRDPS rolled back
    assert "Undone" in res.agent_message
    assert "Rolled back" in (res.confirmation or "")


def test_prose_undo_with_empty_stack_is_honest(tmp_path, monkeypatch):
    from app import chatter as C
    monkeypatch.setattr(C, "check_ollama_for_model", lambda *a, **k: None)

    class _Prov:
        def generate_json(self, system, user, schema):
            return _Resp({"reply": "Undone.", "patch": [{"op": "undo"}]})

    monkeypatch.setattr(C, "get_provider", lambda *a, **k: _Prov())
    s = C.ChatSession(project_name="undoempty", session_dir=tmp_path,
                      username="t")
    res = s.send("undo that please")
    assert "nothing to undo" in res.agent_message.lower()
