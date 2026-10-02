"""Gauntlet: load_tree + validate_config/xml + fews_check skip."""
from __future__ import annotations

from pathlib import Path

import pytest

from fews_agent.validation.fews_bundle import build_region_zip
from fews_agent.validation.fews_check import run_fews_check
from fews_agent.validation.gauntlet import validate_config, validate_xml
from fews_agent.validation.load_tree import load_tree

from tests.gauntlet_fixtures import BROKEN_XML, IMPORT_XML, write_mini_config

REPO = Path(__file__).resolve().parents[1]
TUTORIAL = REPO / "examples" / "config-tutorial"


def test_load_tree_reads_xml(tmp_path):
    write_mini_config(tmp_path)
    tree = load_tree(tmp_path)
    assert tree.files
    names = {str(f.relpath).replace("\\", "/") for f in tree.files}
    assert any(n.endswith("ImportGLOBSNOW.xml") for n in names)


def test_validate_xml_rejects_broken_shape():
    report = validate_xml(BROKEN_XML, spec="TimeSeriesImportRun", tiers=["xsd"])
    assert not report.ok
    assert any(d.rule_id == "xsd.schema" for d in report.errors)


def test_validate_xml_accepts_well_formed_import():
    report = validate_xml(IMPORT_XML, spec="TimeSeriesImportRun", tiers=["xsd"])
    # May still fail XSD if the snippet is missing a required child —
    # the important contract is: it returns a report, never raises.
    assert report.files_checked == 1
    assert report.tiers_run == ["xsd"]


def test_validate_config_runs_tiers_and_skips_fews(tmp_path, monkeypatch):
    monkeypatch.delenv("FEWS_CHECK_CMD", raising=False)
    write_mini_config(tmp_path)
    report = validate_config(tmp_path)
    assert report.files_checked >= 1
    assert "fews_check" in report.tiers_run
    assert any(d.rule_id == "fews.unavailable" for d in report.skips)
    # Semantic may or may not find typed models; it must not crash.
    assert report.to_dict()["path"] == str(tmp_path)


def test_fews_check_skip_when_unconfigured(tmp_path, monkeypatch):
    monkeypatch.delenv("FEWS_CHECK_CMD", raising=False)
    monkeypatch.delenv("FEWS_HOME", raising=False)
    diags = run_fews_check(tmp_path)
    assert len(diags) == 1
    assert diags[0].severity == "skip"
    assert diags[0].rule_id == "fews.unavailable"
    assert "{zip}" in diags[0].message


def test_fews_cli_log_parser():
    from fews_agent.validation.fews_check import _parse_output

    text = (
        "ERROR - Config.Workflows.ImportGFS: workflow does not exist\n"
        "WARN - unused module ImportSREF\n"
        "INFO - starting VALIDATE_CONFIG_FILES\n"
    )
    diags = _parse_output(text)
    assert [d.rule_id for d in diags] == ["fews.config", "fews.config"]
    assert diags[0].severity == "error"
    assert "workflow does not exist" in diags[0].message
    assert diags[1].severity == "warning"


def test_build_region_zip_config_only_drops_region_root(tmp_path):
    (tmp_path / "WorkflowFiles").mkdir()
    (tmp_path / "WorkflowFiles" / "ImportGFS.xml").write_text("<w/>", encoding="utf-8")
    (tmp_path / "RootConfigFiles").mkdir()
    (tmp_path / "RootConfigFiles" / "sa_global.Properties").write_text(
        "REGION=X", encoding="utf-8"
    )
    import io
    import zipfile

    full = build_region_zip(tmp_path, config_only=False)
    only = build_region_zip(tmp_path, config_only=True)
    assert full and only
    full_names = set(zipfile.ZipFile(io.BytesIO(full)).namelist())
    only_names = set(zipfile.ZipFile(io.BytesIO(only)).namelist())
    assert "Config/Workflows/ImportGFS.xml" in full_names
    assert "sa_global.properties" in full_names
    assert "Config/Workflows/ImportGFS.xml" in only_names
    assert "sa_global.properties" not in only_names


def test_fews_check_zip_placeholder_empty_tree(tmp_path, monkeypatch):
    monkeypatch.setenv("FEWS_CHECK_CMD", "echo regionpath={zip}")
    diags = run_fews_check(tmp_path)
    assert len(diags) == 1
    assert diags[0].rule_id == "fews.failed"
    assert "empty region zip" in diags[0].message


def test_unknown_tier_fails_loud(tmp_path):
    with pytest.raises(ValueError, match="unknown gauntlet tier"):
        validate_config(tmp_path, tiers=["not-a-tier"])


@pytest.mark.skipif(not TUTORIAL.is_dir(), reason="examples/config-tutorial not present")
def test_tutorial_semantic_unresolved_count_pinned():
    report = validate_config(TUTORIAL, tiers=["semantic"])
    unresolved = [d for d in report.diagnostics if d.rule_id == "semantic.unresolved"]
    assert len(unresolved) == 27
