"""Per-project git change tracking — diffs of PRE-EXISTING files only.

Each session dir gets its own local git repo (no remotes). After every agent
action ``commit_and_diff`` shows unified diffs for files that existed BEFORE
the action and were modified by it — first-time files are committed silently
and become diffable from the next action on.

Confinement is the critical property: ``projects/`` sits inside the
development repository's tree, so every git command runs with explicit
``--git-dir``/``--work-tree`` and can never walk up to the dev repo.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app import project_git

pytestmark = pytest.mark.skipif(
    not project_git.available(), reason="git binary not on PATH",
)


@pytest.fixture()
def session(tmp_path):
    d = tmp_path / "projects" / "demo" / "demo_2026-07-22_120000"
    (d / "generated" / "RegionConfigFiles").mkdir(parents=True)
    (d / "generated" / "RegionConfigFiles" / "Locations.xml").write_text(
        "<locations>\n  <a/>\n</locations>\n", encoding="utf-8")
    (d / "project.yaml").write_text("name: demo\n", encoding="utf-8")
    (d / ".chat_state.json").write_text("{}", encoding="utf-8")
    return d


def test_first_action_shows_no_diffs_but_sets_baseline(session):
    assert project_git.commit_and_diff(session, "first build") == []
    assert (session / ".git").is_dir()


def test_modified_preexisting_file_is_diffed(session):
    project_git.commit_and_diff(session, "baseline")
    f = session / "generated" / "RegionConfigFiles" / "Locations.xml"
    f.write_text("<locations>\n  <a/>\n  <b/>\n</locations>\n",
                 encoding="utf-8")
    diffs = project_git.commit_and_diff(session, "rebuild")
    assert len(diffs) == 1
    name, text = diffs[0]
    assert name == "generated/RegionConfigFiles/Locations.xml"
    assert "+  <b/>" in text
    # committed → the same change is not reported twice
    assert project_git.commit_and_diff(session, "noop") == []


def test_new_files_are_never_shown_but_become_diffable(session):
    project_git.commit_and_diff(session, "baseline")
    new = session / "generated" / "RegionConfigFiles" / "Topology.xml"
    new.write_text("<topology/>\n", encoding="utf-8")
    assert project_git.commit_and_diff(session, "adds topology") == []
    # ...but the NEXT modification of it shows a diff
    new.write_text("<topology>\n  <node/>\n</topology>\n", encoding="utf-8")
    diffs = project_git.commit_and_diff(session, "changes topology")
    assert [d[0] for d in diffs] == ["generated/RegionConfigFiles/Topology.xml"]


def test_chat_state_and_bulk_inputs_are_ignored_but_csvs_tracked(session):
    """Chat noise and bulk uploads (shapefiles, yamls) never show; input
    CSVs are tracked since the agent can now WRITE them — a first write
    baselines silently, an edit shows a diff."""
    project_git.commit_and_diff(session, "baseline")
    (session / ".chat_state.json").write_text('{"x": 1}', encoding="utf-8")
    (session / "inputs").mkdir()
    (session / "inputs" / "basin.shp").write_bytes(b"\x00\x01")
    csv_file = session / "inputs" / "locations.csv"
    csv_file.write_text("id,lat,lon\nA,1.0,2.0\n", encoding="utf-8")
    assert project_git.commit_and_diff(session, "upload") == []  # all new/ignored
    csv_file.write_text("id,lat,lon\nA,1.0,2.0\nB,3.0,4.0\n", encoding="utf-8")
    diffs = project_git.commit_and_diff(session, "agent adds B")
    assert [d[0] for d in diffs] == ["inputs/locations.csv"]
    assert "+B,3.0,4.0" in diffs[0][1]
    # ...while the shapefile stays invisible forever.
    (session / "inputs" / "basin.shp").write_bytes(b"\x00\x02")
    assert project_git.commit_and_diff(session, "shp noise") == []


def test_old_repos_pick_up_the_csv_rule(session):
    """A session repo created with the old blanket inputs/ ignore gets its
    .gitignore refreshed on the next action."""
    project_git.commit_and_diff(session, "baseline")
    (session / ".gitignore").write_text(
        ".chat_state.json\ninputs/\n", encoding="utf-8")
    project_git.commit_and_diff(session, "next action")
    assert "!inputs/*.csv" in (session / ".gitignore").read_text(
        encoding="utf-8")


def test_commands_are_confined_to_the_session_repo(session, tmp_path):
    """A session dir with NO repo must never fall through to a parent repo."""
    # Simulate the dangerous layout: a parent repo above the session.
    parent_repo = tmp_path / "projects"
    subprocess.run(["git", "init", str(parent_repo)], capture_output=True)
    bare = tmp_path / "projects" / "demo" / "no_repo_session"
    bare.mkdir(parents=True)
    (bare / "file.txt").write_text("x", encoding="utf-8")
    project_git.commit_and_diff(bare, "test")
    # the parent repo saw NOTHING staged/committed from our commands
    status = subprocess.run(
        ["git", "-C", str(parent_repo), "status", "--porcelain"],
        capture_output=True, text=True,
    ).stdout
    assert "no_repo_session/.git" in status or "demo/" in status
    log = subprocess.run(
        ["git", "-C", str(parent_repo), "log", "--oneline"],
        capture_output=True, text=True,
    ).stdout
    assert "test" not in log            # our label never reached the parent


def test_format_diffs_renders_fenced_blocks():
    text = project_git.format_diffs(
        [("a/b.xml", "--- a\n+++ b\n+<x/>")])
    assert "```diff" in text
    assert "new files not shown" in text
    assert project_git.format_diffs([]) == ""


def test_git_missing_is_a_graceful_noop(session, monkeypatch):
    monkeypatch.setattr(project_git, "available", lambda: False)
    assert project_git.commit_and_diff(session, "x") == []


def test_chatter_build_reply_includes_diff(tmp_path, monkeypatch):
    """Integration: build → change resolution → rebuild shows a ```diff."""
    from app import chatter as C
    monkeypatch.setattr(C, "check_ollama_for_model", lambda *a, **k: None)

    class _Boom:
        def generate_json(self, *a, **k):
            raise AssertionError("no LLM in this test")

    monkeypatch.setattr(C, "get_provider", lambda *a, **k: _Boom())
    s = C.ChatSession(project_name="gitdemo", session_dir=tmp_path,
                      username="t")
    s.send("/module processing")
    s.send("/add GFS")
    first = s.send("/build")
    assert "```diff" not in first.agent_message      # first build: all new
    s.send("/set GFS resolution half-degree")
    second = s.send("/build")
    assert "```diff" in second.agent_message         # pre-existing file changed
    assert "gfs_0p50" in second.agent_message
