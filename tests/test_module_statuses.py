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
    # Labels are the short form (no parenthetical), anchored to the real
    # FEWS folder names.
    assert st["processing"]["label"] == "ModuleConfigFiles + WorkflowFiles"
    assert st["root"]["label"] == "RootConfigFiles"


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


# --- stale / forced (amber) -------------------------------------------------

def test_built_module_goes_stale_when_content_changes(session):
    """PDF finding: edit after build kept the healthy green. Now the stamp
    recorded at build time mismatches the changed content -> stale."""
    session.state["slots"]["imports"] = ["GFS"]
    session.state["intent"] = "build_data_import_only"
    session.state["built_phases"] = ["imports"]
    session._stamp_module_fingerprint("processing")
    st = _by_key(session.module_statuses())
    assert st["processing"]["status"] == "built"
    # ...the user changes GFS's resolution after the build...
    session.state["slots"].setdefault("import_overrides", {}).setdefault(
        "GFS", {})["grid_resolution"] = "0p50"
    st = _by_key(session.module_statuses())
    assert st["processing"]["status"] == "stale"
    assert st["processing"]["built"]              # files DO exist
    # rebuilding re-stamps -> healthy green again
    session._stamp_module_fingerprint("processing")
    st = _by_key(session.module_statuses())
    assert st["processing"]["status"] == "built"


def test_forced_assembly_shows_amber_not_green(session):
    """PDF finding: /force-done through missing CSVs lit every deriver
    green. Forced assemblies now read as 'forced' until a clean done."""
    session.state["slots"]["imports"] = ["GFS"]
    session.state["full_build_ok"] = True
    session.state["full_build_forced"] = True
    st = _by_key(session.module_statuses())
    for key in ("locations", "filters", "topology", "root"):
        assert st[key]["status"] == "forced"
        assert st[key]["built"]
    session.state["full_build_forced"] = False
    st = _by_key(session.module_statuses())
    assert st["topology"]["status"] == "built"


def test_deriver_modules_go_stale_on_any_project_change(session):
    """Derived files (Topology, LocationSets, ...) depend on the WHOLE
    project - any change after assembly stales them."""
    session.state["slots"]["imports"] = ["GFS"]
    session.state["intent"] = "build_data_import_only"
    session.state["full_build_ok"] = True
    for key in ("topology", "filters", "locations", "root"):
        session._stamp_module_fingerprint(key)
    st = _by_key(session.module_statuses())
    assert st["topology"]["status"] == "built"
    session.state["slots"]["imports"] = ["GFS", "HRDPS"]
    session._resolve_patterns()
    st = _by_key(session.module_statuses())
    assert st["topology"]["status"] == "stale"
