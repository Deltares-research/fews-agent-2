"""`requires_basin: true` -- bundled standards that only make sense with a
basin model instance in the project.

Colleague-reported: a GFS-only, no-basin project shipped RavenParameters.xml,
ModuleInstanceSets.xml, SetForecastLengthTemplate.xml, and a $MODELNAME1$Grid
entry in Grids.xml -- all Raven-basin content, unconditionally included
regardless of whether the project has a basin at all. Fixed with one
declarative gate in _render_yaml_inputs (checked against the already-computed
basin_count) instead of three bespoke conditions.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from rich.console import Console

from runners.agent.build_from_blueprint import build_from_blueprint

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "fews_agent" / "patterns"


def _build(tmp_path, patterns):
    bp = {"name": "t", "output_root": "out", "patterns": patterns,
          "singleton_seeds": {"Locations": {"geoDatum": "WGS 1984"}}}
    proj = tmp_path / "project.yaml"
    proj.write_text(yaml.safe_dump(bp), encoding="utf-8")
    return build_from_blueprint(
        blueprint_path=proj, pattern_root=PATTERNS_ROOT,
        console=Console(quiet=True),
    )


_BASIN_ONLY_PATHS = (
    "ModuleParFiles/RavenParameters.xml",
    "RegionConfigFiles/ModuleInstanceSets.xml",
    "ModuleConfigFiles/Preprocess/SetForecastLength/SetForecastLengthTemplate.xml",
)


def test_basin_only_standards_absent_with_no_basin(tmp_path):
    summary = _build(tmp_path, [
        {"pattern": "auto/gfs/deterministic", "instances": [{"nwp_name": "GFS"}]},
    ])
    assert summary["ok"], summary.get("errors")
    paths = {f["path"] for f in summary["files"]}
    for p in _BASIN_ONLY_PATHS:
        assert p not in paths, f"{p} should be absent from a no-basin project"
    grids = (Path(tmp_path) / "out" / "RegionConfigFiles" / "Grids.xml").read_text(
        encoding="utf-8",
    )
    assert "$MODELNAME1$Grid" not in grids


def test_basin_only_standards_present_with_a_basin(tmp_path):
    summary = _build(tmp_path, [
        {"pattern": "auto/basin/raven", "instances": [{"basin_name": "Liard"}]},
    ])
    assert summary["ok"], summary.get("errors")
    paths = {f["path"] for f in summary["files"]}
    for p in _BASIN_ONLY_PATHS:
        assert p in paths, f"{p} should still be present with a basin instance"
    grids = (Path(tmp_path) / "out" / "RegionConfigFiles" / "Grids.xml").read_text(
        encoding="utf-8",
    )
    assert "$MODELNAME1$Grid" in grids
