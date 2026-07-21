"""Sidebar module navigator statuses — grey/green/focused per FEWS module."""
from __future__ import annotations

import pytest

from app import chatter as C


@pytest.fixture()
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "check_ollama_for_model", lambda *a, **k: None)
    return C.ChatSession(project_name="statusdemo", session_dir=tmp_path,
                         username="tester")


def _by_key(statuses):
    return {s["key"]: s for s in statuses}


def test_fresh_session_all_grey_none_focused(session):
    st = _by_key(session.module_statuses())
    assert set(st) == {"locations", "parameters", "processing", "display",
                       "filters", "topology", "idmap", "system", "root"}
    assert not any(s["built"] for s in st.values())
    assert not any(s["focused"] for s in st.values())
    # Labels are the short form (no parenthetical).
    assert st["processing"]["label"] == "Processing"


def test_focus_follows_module_command(session):
    session.send("/module processing")
    st = _by_key(session.module_statuses())
    assert st["processing"]["focused"]
    session.send("/module display")
    st = _by_key(session.module_statuses())
    assert st["display"]["focused"] and not st["processing"]["focused"]


def test_processing_goes_green_when_its_phases_are_built(session):
    session.state["slots"]["imports"] = ["GFS"]
    session.state["intent"] = "build_data_import_only"
    st = _by_key(session.module_statuses())
    assert not st["processing"]["built"]          # content, not built yet
    session.state["built_phases"] = ["imports"]
    st = _by_key(session.module_statuses())
    assert st["processing"]["built"]              # its only phase is built
    assert not st["display"]["built"]             # no display content


def test_deriver_modules_green_only_after_full_build(session):
    session.state["slots"]["imports"] = ["GFS"]
    session.state["built_phases"] = ["imports"]
    st = _by_key(session.module_statuses())
    for key in ("locations", "filters", "topology", "root"):
        assert not st[key]["built"]
    session.state["full_build_ok"] = True
    st = _by_key(session.module_statuses())
    for key in ("locations", "filters", "topology", "root"):
        assert st[key]["built"]
