"""nwp_grid_noaa_gefs — NOAA GEFS ensemble import.

Farmed from FEWS-Conform ImportGefs.xml. Distinct shape from the
deterministic nwp_grid_noaa (GFS): the ensemble is TWO <import> blocks —
perturbed members via a %COUNTER(01-30-1)% loop (gep01..gep30) and the
control member (gec00) — both ensembleId-tagged so they land in one
ensemble. These tests render it through expand() and pin the ensemble
mechanics + XSD validity.
"""
from __future__ import annotations

from pathlib import Path

from fews_agent.agent.blueprint import Blueprint, PatternRef, expand
from fews_agent.validation.xsd import validate_xsd

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "fews_agent" / "patterns"
PATTERN = "auto/gfs/ensemble"


def _render(inst=None):
    bp = Blueprint(
        name="gefs-test", output_root=Path("out"),
        patterns=[PatternRef(pattern=PATTERN, instances=[inst or {}])],
    )
    res = expand(bp, PATTERNS_ROOT)
    assert not res.errors, res.errors
    return {rf.relpath.replace("\\", "/"): rf.content for rf in res.rendered_files}


def test_gefs_ensemble_two_block_import():
    files = _render()
    mc = files["ModuleConfigFiles/Import/ImportGefs.xml"]
    ok, msg = validate_xsd(mc.encode("utf-8"))
    assert ok, msg
    # Two <import> blocks: perturbed members + control.
    assert mc.count("<import>") == 2
    assert "file=gep%COUNTER(01-30-1)%" in mc      # member-loop URL
    assert "file=gec00." in mc                     # control member
    assert "<importType>NomadsGribFilterServer</importType>" in mc
    assert "<dataFeedId>Noaa.Gefs</dataFeedId>" in mc
    # Every timeSeriesSet (2 params x 2 blocks) is ensemble-tagged.
    assert mc.count("<ensembleId>Gefs</ensembleId>") == 4
    assert mc.count("<synchLevel>6</synchLevel>") == 4
    # Subregion bbox placeholders survive.
    assert "%TOP_LAT%" in mc and "%BOTTOM_LAT%" in mc
    # idMap + workflow emitted.
    assert "IdMapFiles/Import/IdMapFromGefs.xml" in files
    assert "WorkflowFiles/Import/ImportGefs.xml" in files


def test_gefs_idmap_maps_grib_names():
    idmap = _render()["IdMapFiles/Import/IdMapFromGefs.xml"]
    assert 'internal="Precipitation" external="Total precipitation"' in idmap
    assert 'internal="AirTemperature" external="Temperature"' in idmap


def test_member_range_parameterised():
    # A smaller ensemble (10 members) flows into both the URL counter.
    mc = _render({"member_range": "01-10-1"})["ModuleConfigFiles/Import/ImportGefs.xml"]
    ok, msg = validate_xsd(mc.encode("utf-8"))
    assert ok, msg
    assert "file=gep%COUNTER(01-10-1)%" in mc
    assert "file=gec00." in mc                     # control block unchanged
