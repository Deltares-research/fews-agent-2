"""import_era5 — the ERA5 (Copernicus) reanalysis import+process chain.

Farmed from FEWS-Conform (ImportEra5 + ForecastStartEra5 + ProcessEra5 +
IdMapFromEra5). A folder-based NetCDF import (pairs with
download_via_python_venv), a forecast-length estimator, a grid->scalar
closestDistance transform onto station + catchment sets, the from-ERA5
idMap, and the workflow. Tests render the whole chain and XSD-validate.
"""
from __future__ import annotations

from pathlib import Path

from fews_agent.agent.blueprint import Blueprint, PatternRef, expand
from fews_agent.validation.xsd import validate_xsd

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "patterns"
PATTERN = "auto/import_era5"


def _render(inst=None):
    bp = Blueprint(
        name="era5-test", output_root=Path("out"),
        patterns=[PatternRef(pattern=PATTERN, instances=[inst or {}])],
    )
    res = expand(bp, PATTERNS_ROOT)
    assert not res.errors, res.errors
    return {rf.relpath.replace("\\", "/"): rf.content for rf in res.rendered_files}


def test_full_chain_renders_and_validates():
    files = _render()
    expected = {
        "ModuleConfigFiles/Import/ImportEra5.xml",
        "ModuleConfigFiles/Import/ForecastStartEra5.xml",
        "ModuleConfigFiles/Import/ProcessEra5.xml",
        "IdMapFiles/Import/IdMapFromEra5.xml",
        "WorkflowFiles/Import/ImportEra5.xml",
    }
    assert expected <= set(files)
    for path in expected:
        ok, msg = validate_xsd(files[path].encode("utf-8"))
        assert ok, (path, msg)


def test_folder_based_reanalysis_import():
    mc = _render()["ModuleConfigFiles/Import/ImportEra5.xml"]
    assert "<importType>NETCDF-CF_GRID</importType>" in mc
    assert "<folder>$ModulesFolder$/DownloadEra5/ToFews</folder>" in mc
    assert "<fileNamePatternFilter>*.nc</fileNamePatternFilter>" in mc
    assert "<dataFeedId>Copernicus.Era5</dataFeedId>" in mc
    assert "<timeZoneOffset>+00:00</timeZoneOffset>" in mc
    assert mc.count("<timeSeriesSet>") == 3            # 3 reanalysis params
    assert mc.count("<tolerance ") == 3
    assert "<timeSeriesType>external historical</timeSeriesType>" in mc


def test_forecast_start_and_process():
    files = _render()
    fs = files["ModuleConfigFiles/Import/ForecastStartEra5.xml"]
    assert "<forecastLengthEstimator" in fs
    assert "<setTime0ToLatestNonMissing>true</setTime0ToLatestNonMissing>" in fs
    proc = files["ModuleConfigFiles/Import/ProcessEra5.xml"]
    assert proc.count("<closestDistance>") == 2        # stations + catchments
    assert "<locationSetId>StationsGhcnd</locationSetId>" in proc
    assert "<locationSetId>CatchmentsWflow</locationSetId>" in proc
    assert "<distanceGeoDatum>WGS 1984</distanceGeoDatum>" in proc


def test_idmap_and_workflow():
    files = _render()
    idm = files["IdMapFiles/Import/IdMapFromEra5.xml"]
    assert idm.count("<map ") == 3
    assert 'externalParameter="Total_precipitation_surface_1_Hour_Accumulation"' in idm
    wf = files["WorkflowFiles/Import/ImportEra5.xml"]
    # Ordered chain: forecast-start -> import -> process.
    assert wf.index("ForecastStartEra5") < wf.index(">ImportEra5<") < wf.index("ProcessEra5")


def test_generalises_to_a_new_source():
    files = _render({"source_name": "Era5Land",
                     "download_folder": "$ModulesFolder$/DownloadEra5Land/ToFews"})
    mc = files["ModuleConfigFiles/Import/ImportEra5Land.xml"]
    ok, msg = validate_xsd(mc.encode("utf-8"))
    assert ok, msg
    assert "<idMapId>IdMapFromEra5Land</idMapId>" in mc
    assert "IdMapFiles/Import/IdMapFromEra5Land.xml" in files
