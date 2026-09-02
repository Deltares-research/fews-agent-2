"""merge_family_variables -- shared variables.yaml per pattern family.

Piloted on patterns/auto/gfs/ (nwp_name, grid_resolution shared by
deterministic + gribfilter; ensemble uses source_name and must NOT inherit
either -- a required shared variable an unrelated sibling never sets would
otherwise break that sibling's build, which is exactly what this module
guards against).
"""
from __future__ import annotations

from pathlib import Path

from fews_agent.agent.blueprint import Blueprint, PatternRef, expand
from fews_agent.agent.pattern_family import merge_family_variables
from fews_agent.agent.project_chat import build_pattern_catalog

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "fews_agent" / "patterns"


def _pattern_dir(tmp_path, family: str, name: str) -> Path:
    d = tmp_path / family / name
    d.mkdir(parents=True)
    return d


def test_shared_variable_merged_when_referenced(tmp_path):
    (tmp_path / "fam").mkdir()
    (tmp_path / "fam" / "variables.yaml").write_text(
        "variables:\n  shared_var:\n    type: str\n    required: true\n",
        encoding="utf-8",
    )
    pat_dir = _pattern_dir(tmp_path, "fam", "p")
    pat_yaml = pat_dir / "pattern.yaml"
    raw = "variables:\n  own_var:\n    type: str\noutputs:\n- x: '{{ shared_var }}'\n"
    pat_yaml.write_text(raw, encoding="utf-8")
    merged = merge_family_variables({"variables": {"own_var": {"type": "str"}}},
                                     pat_yaml, raw)
    assert "shared_var" in merged["variables"]
    assert "own_var" in merged["variables"]


def test_shared_variable_skipped_when_not_referenced(tmp_path):
    (tmp_path / "fam").mkdir()
    (tmp_path / "fam" / "variables.yaml").write_text(
        "variables:\n  shared_var:\n    type: str\n    required: true\n",
        encoding="utf-8",
    )
    pat_dir = _pattern_dir(tmp_path, "fam", "p")
    pat_yaml = pat_dir / "pattern.yaml"
    raw = "variables:\n  own_var:\n    type: str\noutputs: []\n"
    pat_yaml.write_text(raw, encoding="utf-8")
    merged = merge_family_variables({"variables": {"own_var": {"type": "str"}}},
                                     pat_yaml, raw)
    assert "shared_var" not in merged["variables"]


def test_comment_only_mention_does_not_count_as_a_reference(tmp_path):
    # A pattern's own comment happening to mention the shared var's name
    # must not be mistaken for real Jinja usage.
    (tmp_path / "fam").mkdir()
    (tmp_path / "fam" / "variables.yaml").write_text(
        "variables:\n  shared_var:\n    type: str\n    required: true\n",
        encoding="utf-8",
    )
    pat_dir = _pattern_dir(tmp_path, "fam", "p")
    pat_yaml = pat_dir / "pattern.yaml"
    raw = "variables:\n  own_var:\n    type: str\n# shared_var isn't used here\noutputs: []\n"
    pat_yaml.write_text(raw, encoding="utf-8")
    merged = merge_family_variables({"variables": {"own_var": {"type": "str"}}},
                                     pat_yaml, raw)
    assert "shared_var" not in merged["variables"]


def test_own_declaration_wins_on_collision(tmp_path):
    (tmp_path / "fam").mkdir()
    (tmp_path / "fam" / "variables.yaml").write_text(
        "variables:\n  x:\n    type: str\n    default: shared\n",
        encoding="utf-8",
    )
    pat_dir = _pattern_dir(tmp_path, "fam", "p")
    pat_yaml = pat_dir / "pattern.yaml"
    raw = "variables:\n  x:\n    type: str\n    default: own\noutputs: []\n"
    pat_yaml.write_text(raw, encoding="utf-8")
    merged = merge_family_variables({"variables": {"x": {"type": "str", "default": "own"}}},
                                     pat_yaml, raw)
    assert merged["variables"]["x"]["default"] == "own"


def test_no_family_file_leaves_spec_unchanged(tmp_path):
    pat_dir = _pattern_dir(tmp_path, "lonely", "p")
    pat_yaml = pat_dir / "pattern.yaml"
    spec = {"variables": {"x": {"type": "str"}}}
    pat_yaml.write_text("variables:\n  x:\n    type: str\noutputs: []\n", encoding="utf-8")
    merged = merge_family_variables(spec, pat_yaml)
    assert merged == spec


# --- real gfs/ family, catalog + real render agree -------------------------

def test_gfs_deterministic_and_gribfilter_inherit_shared_vars():
    catalog = build_pattern_catalog(PATTERNS_ROOT)
    by_path = {p.path: p for p in catalog}
    assert "nwp_name" in by_path["auto/gfs/deterministic"].variables
    assert "grid_resolution" in by_path["auto/gfs/deterministic"].variables
    assert "nwp_name" in by_path["auto/gfs/gribfilter"].variables
    assert "grid_resolution" in by_path["auto/gfs/gribfilter"].variables


def test_gfs_ensemble_does_not_inherit_unused_shared_vars():
    catalog = build_pattern_catalog(PATTERNS_ROOT)
    ensemble = next(p for p in catalog if p.path == "auto/gfs/ensemble")
    assert "nwp_name" not in ensemble.variables
    assert "grid_resolution" not in ensemble.variables


def test_gfs_ensemble_still_builds_without_nwp_name():
    bp = Blueprint(name="t", output_root=Path("out"), patterns=[
        PatternRef(pattern="auto/gfs/ensemble", instances=[{"source_name": "Gefs"}]),
    ])
    res = expand(bp, PATTERNS_ROOT)
    assert not res.errors, res.errors


def test_gfs_deterministic_and_gribfilter_still_build_with_shared_vars():
    bp = Blueprint(name="t", output_root=Path("out"), patterns=[
        PatternRef(pattern="auto/gfs/deterministic", instances=[{"nwp_name": "GFS"}]),
        PatternRef(pattern="auto/gfs/gribfilter", instances=[{"nwp_name": "GFS"}]),
    ])
    res = expand(bp, PATTERNS_ROOT)
    assert not res.errors, res.errors
    paths = {rf.relpath for rf in res.rendered_files}
    assert "ModuleConfigFiles/Import/NOAA/ImportGFS.xml" in paths
