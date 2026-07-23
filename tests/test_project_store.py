"""The app's projects/ store — the project-picker's backing helpers.

Pure filesystem logic (no Streamlit, no LLM): mint a new project session,
list resumable projects, resolve the latest session. Layout matches the CLI
and HTTP API: ``projects/<name>/<name>_<YYYY-MM-DD_HHMMSS>/``.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "app"))

import chatter  # noqa: E402


def test_safe_project_name_sanitizes():
    assert chatter.safe_project_name("Liard Forecast") == "Liard-Forecast"
    assert chatter.safe_project_name("a/b:c") == "a-b-c"
    assert chatter.safe_project_name("keep-._ok") == "keep-._ok"
    assert chatter.safe_project_name("   ") == "project"  # empty → fallback


def test_new_project_session_dir_layout(tmp_path):
    sd = chatter.new_project_session_dir("liard forecast", root=tmp_path)
    # projects/<safe>/<safe>_<dt>/
    assert sd.parent.name == "liard-forecast"
    assert sd.name.startswith("liard-forecast_")
    assert sd.is_dir()


def test_list_projects_only_shows_ones_with_chat_state(tmp_path):
    # A build-only fixture (project.yaml, no chat state) must NOT appear.
    fixture = tmp_path / "buildonly" / "buildonly_2026-01-01_000000"
    fixture.mkdir(parents=True)
    (fixture / "project.yaml").write_text("name: buildonly")
    assert chatter.list_projects(root=tmp_path) == []

    # A real chat session shows up.
    sd = chatter.new_project_session_dir("real", root=tmp_path)
    (sd / ".chat_state.json").write_text("{}")
    assert chatter.list_projects(root=tmp_path) == ["real"]


def test_latest_project_session_dir_picks_newest(tmp_path):
    parent = tmp_path / "p"
    parent.mkdir()
    older = parent / "p_2026-01-01_000000"
    newer = parent / "p_2026-06-01_120000"
    older.mkdir()
    newer.mkdir()
    assert chatter.latest_project_session_dir("p", root=tmp_path) == newer
    assert chatter.latest_project_session_dir("missing", root=tmp_path) is None


def test_new_project_lists_and_resumes_roundtrip(tmp_path):
    # Create → write state → it's listable → latest resolves to it.
    sd = chatter.new_project_session_dir("demo", root=tmp_path)
    (sd / ".chat_state.json").write_text("{}")
    assert "demo" in chatter.list_projects(root=tmp_path)
    assert chatter.latest_project_session_dir("demo", root=tmp_path) == sd


def test_session_persists_at_open_not_first_turn(tmp_path, monkeypatch):
    """Creating/opening a session writes state (and fires the blob sync)
    IMMEDIATELY - a project must exist in the store before any turn runs."""
    from app import chatter as C
    from app import blob_store
    synced = []
    monkeypatch.setattr(C, "check_ollama_for_model", lambda *a, **k: None)
    monkeypatch.setattr(blob_store, "sync_session_up",
                        lambda d, full=False: synced.append(str(d)) or 0)
    s = C.ChatSession(project_name="instant", session_dir=tmp_path,
                      username="t")
    assert (tmp_path / ".chat_state.json").is_file()   # no turn taken yet
    assert synced, "blob sync must fire at session open"
