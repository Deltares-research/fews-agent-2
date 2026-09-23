"""Shared toolbelt functions (MCP and HTTP both wrap these)."""
from __future__ import annotations

from fews_agent.validation.examples import find_examples
from fews_agent.validation.toolbelt import (
    tool_explain_diagnostic,
    tool_find_examples,
    tool_id_registry,
    tool_validate_config,
    tool_validate_xml,
)

from tests.gauntlet_fixtures import BROKEN_XML, write_mini_config


def test_validate_xml_tool_broken():
    out = tool_validate_xml(BROKEN_XML, spec="TimeSeriesImportRun")
    assert out["ok"] is False
    assert out["error_count"] >= 1


def test_validate_config_and_id_registry(tmp_path, monkeypatch):
    monkeypatch.delenv("FEWS_CHECK_CMD", raising=False)
    write_mini_config(tmp_path)
    out = tool_validate_config(str(tmp_path))
    assert "diagnostics" in out
    assert out["files_checked"] >= 1
    reg = tool_id_registry(str(tmp_path))
    assert "declared" in reg
    assert "unresolved" in reg


def test_explain_known_rules():
    xsd = tool_explain_diagnostic("xsd.schema")
    assert xsd["rule_id"] == "xsd.schema"
    assert "example" in xsd
    casing = tool_explain_diagnostic("conform.idmap_casing")
    assert "GLOBSNOW" in casing["citation"]
    assert "IdImportGlobSnow" in casing.get("example", "")
    unknown = tool_explain_diagnostic("no.such.rule")
    assert "error" in unknown


def test_find_examples_patterns():
    hits = find_examples("nwp_grid_noaa", k=3)
    # Pattern library is always present; at least the pattern.yaml should match.
    assert isinstance(hits, list)
    wrapped = tool_find_examples("GFS", k=2)
    assert wrapped["query"] == "GFS"
