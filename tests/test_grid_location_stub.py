"""_stub_missing_grid_locations -- grid locationIds (GFS, HRDPS, ...) get a
placeholder <location> entry in Locations.xml.

Colleague-reported: ImportGFS.xml references locationId=GFS directly, but
nothing declared it anywhere -- a genuinely unresolved semantic reference in
a fresh (non-tutorial) project. locationsets_derivation.py only stubs
locationSetId references, a structurally different thing; confirmed against
the real tutorial reproduction that grid names belong in Locations.xml as
plain <location> entries, never LocationSets.xml.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from rich.console import Console

from runners.agent.build_from_blueprint import (
    _stub_missing_grid_locations,
    build_from_blueprint,
)
from fews_agent.validation.xsd import validate_xsd

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "fews_agent" / "patterns"

_BASE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<locations version="1.1" xmlns="http://www.wldelft.nl/fews" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
    '  <geoDatum>WGS 1984</geoDatum>\n'
    '  <location id="Loc1" name="Station 1"><x>5.0</x><y>50.0</y></location>\n'
    '</locations>\n'
)


# --- pure unit tests on the graft function ----------------------------------

def test_stubs_a_missing_grid_id():
    out = _stub_missing_grid_locations(_BASE_XML, {"GFS"})
    assert '<location id="GFS" name="GFS">' in out
    ok, msg = validate_xsd(out.encode("utf-8"))
    assert ok, msg


def test_no_op_when_already_declared():
    out = _stub_missing_grid_locations(_BASE_XML, {"Loc1"})
    assert out == _BASE_XML


def test_multiple_missing_ids_all_stubbed():
    out = _stub_missing_grid_locations(_BASE_XML, {"GFS", "HRDPS"})
    assert '<location id="GFS"' in out
    assert '<location id="HRDPS"' in out
    ok, msg = validate_xsd(out.encode("utf-8"))
    assert ok, msg


def test_new_entries_placed_after_existing_locations_not_before():
    out = _stub_missing_grid_locations(_BASE_XML, {"GFS"})
    assert out.index('id="Loc1"') < out.index('id="GFS"')


# --- integration: real build --------------------------------------------

def _build(tmp_path, patterns, inputs_dir=None):
    bp = {"name": "t", "output_root": "out", "patterns": patterns,
          "singleton_seeds": {"Locations": {"geoDatum": "WGS 1984"}}}
    proj = tmp_path / "project.yaml"
    proj.write_text(yaml.safe_dump(bp), encoding="utf-8")
    return build_from_blueprint(
        blueprint_path=proj, pattern_root=PATTERNS_ROOT,
        inputs_dir=inputs_dir, console=Console(quiet=True),
    )


def test_gfs_locationid_no_longer_unresolved_with_a_locations_csv(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "locations.csv").write_text(
        "FewsId,Name,Lat,Lon,Alt\nLoc1,Station 1,50.0,5.0,0\n",
        encoding="utf-8",
    )
    summary = _build(
        tmp_path,
        [{"pattern": "auto/gfs/deterministic", "instances": [{"nwp_name": "GFS"}]}],
        inputs_dir=inputs,
    )
    assert summary["ok"], summary.get("errors")
    assert "GFS (locationId)" not in "\n".join(summary["semantic_unresolved"])
    locations = (Path(tmp_path) / "out" / "RegionConfigFiles" / "Locations.xml").read_text(
        encoding="utf-8",
    )
    assert 'id="GFS"' in locations


def test_no_crash_and_no_stub_without_any_locations_file(tmp_path):
    summary = _build(
        tmp_path,
        [{"pattern": "auto/gfs/deterministic", "instances": [{"nwp_name": "GFS"}]}],
    )
    assert summary["ok"], summary.get("errors")
    paths = {f["path"] for f in summary["files"]}
    assert "RegionConfigFiles/Locations.xml" not in paths
