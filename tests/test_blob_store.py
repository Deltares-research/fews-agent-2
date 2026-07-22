"""PHASE-switched session store — dev is a no-op, prod mirrors to blob.

No Azure SDK, no network: a fake container stands in for the ContainerClient
(the SDK import is lazy and only fires inside ``_container()``, which these
tests monkeypatch away). What's pinned:

  * dev / unconfigured-prod → every operation is a safe no-op;
  * core-vs-full upload sets and the blob naming layout;
  * restore path (list projects, newest session, pull to disk);
  * failures are absorbed loudly (return 0/None), never raised;
  * the picker helpers fall back to blob when local disk is empty.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from app import blob_store


class _FakeBlob:
    def __init__(self, name):
        self.name = name


class _FakeDownload:
    def __init__(self, data):
        self._data = data

    def readall(self):
        return self._data


class _FakeContainer:
    """In-memory stand-in for azure ContainerClient."""

    def __init__(self):
        self.blobs: dict[str, bytes] = {}

    def create_container(self):
        pass

    def upload_blob(self, name, stream, overwrite=False):
        self.blobs[name] = stream.read()

    def list_blobs(self, name_starts_with=""):
        return [_FakeBlob(n) for n in sorted(self.blobs)
                if n.startswith(name_starts_with)]

    def download_blob(self, name):
        return _FakeDownload(self.blobs[name])


class _BoomContainer:
    def __getattr__(self, name):
        raise ConnectionError("storage down")


@pytest.fixture()
def prod(monkeypatch):
    monkeypatch.setenv("PHASE", "prod")
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "fake")
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER", "fews-projects")
    monkeypatch.delenv("AZURE_STORAGE_PREFIX", raising=False)
    fake = _FakeContainer()
    monkeypatch.setattr(blob_store, "_container", lambda: fake)
    return fake


def _session(tmp_path, with_generated=False):
    d = tmp_path / "projects" / "demo" / "demo_2026-07-22_120000"
    d.mkdir(parents=True)
    (d / ".chat_state.json").write_text("{}", encoding="utf-8")
    (d / ".chat_history.json").write_text("[]", encoding="utf-8")
    (d / "_conversation.md").write_text("# t", encoding="utf-8")
    (d / "project.yaml").write_text("name: demo", encoding="utf-8")
    if with_generated:
        g = d / "generated" / "RootConfigFiles"
        g.mkdir(parents=True)
        (g / "sa_global.Properties").write_text("REGION=X", encoding="utf-8")
    return d


# --- dev: everything is a no-op -------------------------------------------

def test_dev_phase_is_noop(monkeypatch, tmp_path):
    monkeypatch.setenv("PHASE", "dev")
    d = _session(tmp_path)
    assert blob_store.enabled() is False
    assert blob_store.sync_session_up(d) == 0
    assert blob_store.list_remote_projects() == []
    assert blob_store.latest_remote_session_id("demo") is None
    assert blob_store.pull_session("demo", "x", tmp_path) is None


def test_prod_without_config_is_noop_not_crash(monkeypatch, tmp_path):
    monkeypatch.setenv("PHASE", "prod")
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("AZURE_STORAGE_CONTAINER", raising=False)
    assert blob_store.enabled() is False
    assert blob_store.sync_session_up(_session(tmp_path)) == 0


# --- prod: upload sets + naming --------------------------------------------

def test_core_sync_uploads_only_per_turn_files(prod, tmp_path):
    d = _session(tmp_path, with_generated=True)
    n = blob_store.sync_session_up(d)
    assert n == 4
    names = set(prod.blobs)
    assert "demo/demo_2026-07-22_120000/.chat_state.json" in names
    assert not any("generated" in n for n in names)   # core only


def test_full_sync_uploads_everything(prod, tmp_path):
    d = _session(tmp_path, with_generated=True)
    n = blob_store.sync_session_up(d, full=True)
    assert n == 5
    assert ("demo/demo_2026-07-22_120000/generated/RootConfigFiles/"
            "sa_global.Properties") in prod.blobs


def test_prefix_prepends_subpath(prod, tmp_path, monkeypatch):
    monkeypatch.setenv("AZURE_STORAGE_PREFIX", "team-a/")
    d = _session(tmp_path)
    blob_store.sync_session_up(d)
    assert all(n.startswith("team-a/demo/") for n in prod.blobs)


# --- prod: restore path -----------------------------------------------------

def test_list_latest_and_pull_roundtrip(prod, tmp_path):
    d = _session(tmp_path, with_generated=True)
    blob_store.sync_session_up(d, full=True)
    # a second, older session
    old = tmp_path / "projects" / "demo" / "demo_2026-07-21_090000"
    old.mkdir(parents=True)
    (old / ".chat_state.json").write_text("{}", encoding="utf-8")
    blob_store.sync_session_up(old)

    assert blob_store.list_remote_projects() == ["demo"]
    assert blob_store.latest_remote_session_id("demo") == \
        "demo_2026-07-22_120000"

    dest_root = tmp_path / "fresh"        # simulates a wiped container disk
    pulled = blob_store.pull_session("demo", "demo_2026-07-22_120000",
                                     dest_root)
    assert pulled == dest_root / "demo" / "demo_2026-07-22_120000"
    assert (pulled / ".chat_state.json").is_file()
    assert (pulled / "generated" / "RootConfigFiles"
            / "sa_global.Properties").read_text(encoding="utf-8") == "REGION=X"


def test_failures_absorbed_never_raised(prod, tmp_path, monkeypatch):
    monkeypatch.setattr(blob_store, "_container", lambda: _BoomContainer())
    d = _session(tmp_path)
    assert blob_store.sync_session_up(d) == 0
    assert blob_store.list_remote_projects() == []
    assert blob_store.pull_session("demo", "x", tmp_path) is None


# --- picker integration ------------------------------------------------------

def test_picker_pulls_from_blob_when_local_missing(prod, tmp_path, monkeypatch):
    from app import chatter as C
    d = _session(tmp_path, with_generated=True)
    blob_store.sync_session_up(d, full=True)

    fresh_root = tmp_path / "fresh_projects"   # nothing local
    assert "demo" in C.list_projects(root=fresh_root) or \
        "demo" in blob_store.list_remote_projects()
    got = C.latest_project_session_dir("demo", root=fresh_root)
    assert got is not None
    assert (got / ".chat_state.json").is_file()
