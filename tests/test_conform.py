"""Conform rule registry — one corpus-cited test per shipped rule."""
from __future__ import annotations

from fews_agent.validation.conform import lint_tree
from fews_agent.validation.gauntlet import validate_xml
from fews_agent.validation.load_tree import load_tree

from tests.gauntlet_fixtures import PARAMETERS_XML, write_mini_config


def test_idmap_casing_detects_globsnow(tmp_path):
    write_mini_config(tmp_path, glob_casing=True)
    diags = lint_tree(load_tree(tmp_path))
    hits = [d for d in diags if d.rule_id == "conform.idmap_casing"]
    assert hits
    assert any("IdImportGlobSnow" in d.message for d in hits)


def test_csv_attr_pascal_flags_underscore(tmp_path):
    write_mini_config(tmp_path)
    diags = lint_tree(load_tree(tmp_path))
    hits = [d for d in diags if d.rule_id == "conform.csv_attr_pascal"]
    assert any("wflow_id" in d.message for d in hits)


def test_filename_id_agreement(tmp_path):
    write_mini_config(tmp_path)
    diags = lint_tree(load_tree(tmp_path))
    hits = [d for d in diags if d.rule_id == "conform.filename_id_agreement"]
    assert any("Filters.xml" in d.file for d in hits)


def test_param_suffix_flags_invalid_id():
    report = validate_xml(PARAMETERS_XML, spec="Parameters", tiers=["conform"])
    hits = [d for d in report.diagnostics if d.rule_id == "conform.param_suffix"]
    assert any("not a valid id" in d.message for d in hits)


def test_matching_idmap_is_silent(tmp_path):
    write_mini_config(tmp_path, glob_casing=False)
    diags = lint_tree(load_tree(tmp_path))
    assert not any(d.rule_id == "conform.idmap_casing" for d in diags)


def test_conform_derived_gefs_pattern_has_zero_findings(tmp_path):
    """FEWS-Conform-farmed GEFS outputs must not trip the house linter."""
    from fews_agent.agent.blueprint import Blueprint, PatternRef, expand

    repo = __import__("pathlib").Path(__file__).resolve().parents[1]
    bp = Blueprint(
        name="gefs-conform-lint",
        output_root=tmp_path,
        patterns=[PatternRef(pattern="auto/nwp_grid_noaa_gefs", instances=[{}])],
    )
    res = expand(bp, repo / "fews_agent" / "patterns")
    assert not res.errors, res.errors
    for rf in res.rendered_files:
        dest = tmp_path / rf.relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(rf.content, encoding="utf-8")
    diags = lint_tree(load_tree(tmp_path))
    hits = [d for d in diags if d.rule_id.startswith("conform.")]
    assert hits == []
