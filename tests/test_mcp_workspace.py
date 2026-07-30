"""MCP workspace_dir routing — sessions land in the user's workspace.

Pure path/index tests (no LLM, no build). Patches the module-level
OUTPUT_ROOT / session-index path so we never touch the real projects/.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import mcp_server as mcp


@pytest.fixture()
def agent_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate the agent-repo projects store + session index under tmp."""
    root = tmp_path / "agent-projects"
    root.mkdir()
    monkeypatch.setattr(mcp, "OUTPUT_ROOT", root)
    monkeypatch.setattr(mcp, "_SESSION_INDEX_PATH", root / ".mcp_session_index.json")
    return root


def test_resolve_projects_root_default(agent_projects: Path):
    root, err = mcp.resolve_projects_root(None)
    assert err is None
    assert root == agent_projects


def test_resolve_projects_root_workspace(tmp_path: Path, agent_projects: Path):
    workspace = tmp_path / "user-ws"
    workspace.mkdir()
    root, err = mcp.resolve_projects_root(str(workspace), create=True)
    assert err is None
    assert root == workspace / "fews-projects"
    assert root.is_dir()


def test_resolve_projects_root_missing_workspace(tmp_path: Path, agent_projects: Path):
    root, err = mcp.resolve_projects_root(str(tmp_path / "nope"), create=True)
    assert root is None
    assert err is not None
    assert "does not exist" in err


def test_create_project_default_uses_agent_repo(agent_projects: Path):
    raw = mcp.create_project(project_name="alpha")
    data = json.loads(raw)
    assert "error" not in data
    project_dir = Path(data["project_dir"])
    assert project_dir.is_relative_to(agent_projects)
    assert (project_dir / ".chat_state.json").is_file()
    assert data["workspace_dir"] is None
    assert data["session_id"] == project_dir.name


def test_create_project_workspace_dir(tmp_path: Path, agent_projects: Path):
    workspace = tmp_path / "my-basin"
    workspace.mkdir()
    raw = mcp.create_project(
        project_name="liard", workspace_dir=str(workspace),
    )
    data = json.loads(raw)
    assert "error" not in data
    project_dir = Path(data["project_dir"])
    assert project_dir.is_relative_to(workspace / "fews-projects")
    assert data["workspace_dir"] == str(workspace.resolve())
    assert "fews-projects" in data["generated_dir"]

    state = json.loads((project_dir / ".chat_state.json").read_text(encoding="utf-8"))
    assert state["workspace_dir"] == str(workspace.resolve())

    # Index lets later tools find the session without re-passing workspace.
    found = mcp._resolve_session_dir(data["session_id"])
    assert found == project_dir


def test_resolve_with_workspace_dir_hint(tmp_path: Path, agent_projects: Path):
    workspace = tmp_path / "ws2"
    workspace.mkdir()
    data = json.loads(mcp.create_project(
        project_name="beta", workspace_dir=str(workspace),
    ))
    # Wipe the index — lookup must still work via workspace_dir.
    mcp._SESSION_INDEX_PATH.write_text("{}", encoding="utf-8")
    found = mcp._resolve_session_dir(
        data["session_id"], workspace_dir=str(workspace),
    )
    assert found is not None
    assert found.name == data["session_id"]


def test_get_status_returns_absolute_paths(tmp_path: Path, agent_projects: Path):
    workspace = tmp_path / "ws3"
    workspace.mkdir()
    created = json.loads(mcp.create_project(
        project_name="gamma", workspace_dir=str(workspace),
    ))
    status = json.loads(mcp.get_status(created["session_id"]))
    assert status["project_dir"] == created["project_dir"]
    assert status["generated_dir"] == created["generated_dir"]
    assert status["workspace_dir"] == created["workspace_dir"]
    assert status["generated_exists"] is False


def test_list_projects_scoped_to_workspace(tmp_path: Path, agent_projects: Path):
    ws_a = tmp_path / "a"
    ws_b = tmp_path / "b"
    ws_a.mkdir()
    ws_b.mkdir()
    a = json.loads(mcp.create_project("proj-a", workspace_dir=str(ws_a)))
    b = json.loads(mcp.create_project("proj-b", workspace_dir=str(ws_b)))
    listed = json.loads(mcp.list_projects(workspace_dir=str(ws_a)))
    ids = {p["session_id"] for p in listed["projects"]}
    assert a["session_id"] in ids
    assert b["session_id"] not in ids


def test_list_projects_default_includes_indexed_workspace(
    tmp_path: Path, agent_projects: Path,
):
    # One in agent repo, one in a foreign workspace.
    local = json.loads(mcp.create_project("local-only"))
    workspace = tmp_path / "foreign"
    workspace.mkdir()
    foreign = json.loads(mcp.create_project(
        "foreign", workspace_dir=str(workspace),
    ))
    listed = json.loads(mcp.list_projects())
    ids = {p["session_id"] for p in listed["projects"]}
    assert local["session_id"] in ids
    assert foreign["session_id"] in ids


def test_rejects_unsafe_session_id(agent_projects: Path):
    assert mcp._resolve_session_dir("../etc") is None
    assert mcp._resolve_session_dir("a/b") is None


def test_patterns_root_points_at_package_library():
    """Patterns live under fews_agent/patterns/ (relocated from repo root)."""
    assert mcp.PATTERNS_ROOT == mcp.REPO_ROOT / "fews_agent" / "patterns"
    assert (mcp.PATTERNS_ROOT / "auto").is_dir()
    catalog = mcp._catalog()
    assert len(catalog) > 0


def test_slash_module_command_bypasses_llm(agent_projects: Path):
    created = json.loads(mcp.create_project("slash-demo"))
    sid = created["session_id"]
    raw = mcp.chat(sid, "/modules")
    data = json.loads(raw)
    assert "error" not in data
    assert data.get("slash_command") is True
    assert data.get("wants_build") is False
    assert "processing" in data["reply"].lower() or "module" in data["reply"].lower()


def test_get_status_includes_route(agent_projects: Path):
    created = json.loads(mcp.create_project("status-demo"))
    sid = created["session_id"]
    data = json.loads(mcp.get_status(sid))
    assert "error" not in data
    assert "route" in data
    assert "ready_to_assemble" in data["route"]
    assert "inputs" in data["route"]


def test_undo_stack_helpers():
    state = {"name": "x", "slots": {"imports": ["GFS"]}, "model": "m1"}
    mcp._push_undo_snapshot(state)
    state["slots"] = {"imports": ["GFS", "HRDPS"]}
    assert mcp._pop_undo_snapshot(state, keep_model="m1")
    assert state["slots"] == {"imports": ["GFS"]}
    assert state["model"] == "m1"
    assert not mcp._pop_undo_snapshot(state)
