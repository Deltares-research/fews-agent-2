"""Sidebar download bundles: per-module zips + the Config skeleton bundle.

The chat shows only the canned generation+XSD summary (which also grounds the
LLM's build digest); the DOWNLOADS live in the left panel. Two helpers back
them, both session-scoped (they read only <session>/generated):

  * ChatSession.module_zip(key)  — one module's rendered files, scoped by the
    registry's folders (dir prefixes + .xml stems for split variants);
  * ChatSession.config_zip()     — everything, wrapped as Config/ with an
    EMPTY directory entry for every standard FEWS folder.
"""
from __future__ import annotations

import io
import zipfile

import pytest

from app import chatter as C
from fews_agent.agent.modules import CONFIG_FOLDERS


@pytest.fixture()
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "check_ollama_for_model", lambda *a, **k: None)
    s = C.ChatSession(project_name="dl", session_dir=tmp_path,
                      username="tester")
    gen = tmp_path / "generated"
    (gen / "ModuleConfigFiles" / "Import").mkdir(parents=True)
    (gen / "WorkflowFiles").mkdir()
    (gen / "RegionConfigFiles").mkdir()
    (gen / "RootConfigFiles").mkdir()
    (gen / "ModuleConfigFiles" / "Import" / "ImportGFS.xml").write_text(
        "<x/>", encoding="utf-8")
    (gen / "WorkflowFiles" / "ImportGFS.xml").write_text("<w/>", encoding="utf-8")
    (gen / "RegionConfigFiles" / "Locations.xml").write_text("<l/>", encoding="utf-8")
    (gen / "RegionConfigFiles" / "FiltersLiard.xml").write_text("<f/>", encoding="utf-8")
    (gen / "RootConfigFiles" / "sa_global.Properties").write_text(
        "REGION=X", encoding="utf-8")
    return s


def _names(zbytes: bytes) -> list[str]:
    return zipfile.ZipFile(io.BytesIO(zbytes)).namelist()


def test_module_zip_scopes_to_the_registry_folders(session):
    data, n = session.module_zip("processing")
    names = _names(data)
    assert n == 2
    assert "ModuleConfigFiles/Import/ImportGFS.xml" in names
    assert "WorkflowFiles/ImportGFS.xml" in names
    assert not any("RegionConfigFiles" in x for x in names)


def test_module_zip_xml_stem_catches_split_variants(session):
    # filters' folder is RegionConfigFiles/Filters.xml — the stem must catch
    # the split FiltersLiard.xml but never Locations.xml.
    data, n = session.module_zip("filters")
    names = _names(data)
    assert names == ["RegionConfigFiles/FiltersLiard.xml"]


def test_module_zip_none_when_module_has_nothing(session):
    assert session.module_zip("display") is None
    assert session.module_zip("nonsense") is None


def test_config_zip_wraps_in_config_with_full_skeleton(session):
    data, n = session.config_zip()
    names = set(_names(data))
    assert n == 5
    # every standard FEWS folder present as a directory entry, even if empty
    for folder in CONFIG_FOLDERS:
        assert f"Config/{folder}/" in names, folder
    # rendered files land inside Config/
    assert "Config/ModuleConfigFiles/Import/ImportGFS.xml" in names
    assert "Config/RootConfigFiles/sa_global.Properties" in names


def test_config_zip_none_before_any_build(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "check_ollama_for_model", lambda *a, **k: None)
    s = C.ChatSession(project_name="empty", session_dir=tmp_path,
                      username="t")
    assert s.config_zip() is None
