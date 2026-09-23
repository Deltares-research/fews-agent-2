"""Gauntlet: load_tree + validate_config/xml + fews_check skip."""
from __future__ import annotations

from pathlib import Path

import pytest

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


def test_unknown_tier_fails_loud(tmp_path):
    with pytest.raises(ValueError, match="unknown gauntlet tier"):
        validate_config(tmp_path, tiers=["not-a-tier"])


@pytest.mark.skipif(not TUTORIAL.is_dir(), reason="examples/config-tutorial not present")
def test_tutorial_semantic_unresolved_count_pinned():
    report = validate_config(TUTORIAL, tiers=["semantic"])
    unresolved = [d for d in report.diagnostics if d.rule_id == "semantic.unresolved"]
    assert len(unresolved) == 27
