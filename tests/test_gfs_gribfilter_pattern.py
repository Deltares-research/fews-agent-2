"""nwp_grid_noaa_gribfilter — NOAA GFS import via the NOMADS grib-filter CGI.

Farmed from a real "extended gfs" FEWS project export. Distinct from the
frozen auto/gfs/deterministic (older DODS/OPeNDAP mechanism, untouched — the
tutorial byte-equivalence oracle depends on its exact output): this pattern
uses importType=NomadsGribFilterServer, TWO <import> blocks split by whether
the GRIB field is an accumulation (P.forecast/Rs.forecast/Rnl.forecast, f003
start, cumulativeSum) or instantaneous (the other 6, f000 start), and carries
9 real GFS variables instead of 2. Wind.u/Wind.v are farmed as raw
components only — Wind.speed.forecast/Wind.dir.forecast are intentionally
NOT derived (the transform that would compute them from u/v isn't in the
source export or anywhere else on disk).
"""
from __future__ import annotations

from pathlib import Path

from fews_agent.agent.blueprint import Blueprint, PatternRef, expand
from fews_agent.agent.project_chat import build_pattern_catalog
from fews_agent.agent.project_intents import (
    _data_types_to_parameter_rows,
    _pattern_vocabularies,
)
from fews_agent.validation.xsd import validate_xsd

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "fews_agent" / "patterns"
PATTERN = "auto/gfs/gribfilter"


def _render(inst=None):
    bp = Blueprint(
        name="gfs-gribfilter-test", output_root=Path("out"),
        patterns=[PatternRef(pattern=PATTERN, instances=[inst or {"nwp_name": "GFS"}])],
    )
    res = expand(bp, PATTERNS_ROOT)
    assert not res.errors, res.errors
    return {rf.relpath.replace("\\", "/"): rf.content for rf in res.rendered_files}


def test_two_import_blocks_instantaneous_vs_accumulated():
    mc = _render()["ModuleConfigFiles/Import/NOAA/ImportGFS.xml"]
    ok, msg = validate_xsd(mc.encode("utf-8"))
    assert ok, msg
    assert mc.count("<import>") == 2
    # Split the two <general> blocks apart to check var placement per block.
    blocks = mc.split("<import>")[1:]
    instantaneous_block, accumulated_block = blocks
    assert "%COUNTER(000-120-3)%" in instantaneous_block
    assert "%COUNTER(003-120-3)%" in accumulated_block
    for var in ("PRMSL", "UGRD", "VGRD", "TMP", "DPT", "TCDC"):
        assert f"var_{var}=on" in instantaneous_block
        assert f"var_{var}=on" not in accumulated_block
    for var in ("APCP", "DSWRF", "DLWRF"):
        assert f"var_{var}=on" in accumulated_block
        assert f"var_{var}=on" not in instantaneous_block
    assert "<importType>NomadsGribFilterServer</importType>" in mc
    assert mc.count("variable_identification_method") == 1
    assert "grib2_parameter_name" in accumulated_block
    assert "grib2_parameter_name" not in instantaneous_block
    for macro in ("%TOP_LAT%", "%LEFT_LON%", "%RIGHT_LON%", "%BOTTOM_LAT%"):
        assert instantaneous_block.count(macro) == 1
        assert accumulated_block.count(macro) == 1


def test_all_cumulative_selection_omits_empty_instantaneous_block():
    # Regression: selecting ONLY cumulative parameters (e.g. just
    # precipitation) must not emit an empty Block 1 -- an empty
    # timeSeriesSet:/externUnit: renders as YAML null, not [], which
    # Pydantic rejects. Block 1 must be skipped entirely when empty, mirroring
    # the {% if accumulated %} guard already on Block 2.
    files = _render({"nwp_name": "GFS", "parameters": [
        {"id": "P.forecast", "unit": "mm", "cumulativeSum": True,
         "gribVar": "APCP", "gribLevel": "surface",
         "external": "Total precipitation"},
    ]})
    mc = files["ModuleConfigFiles/Import/NOAA/ImportGFS.xml"]
    ok, msg = validate_xsd(mc.encode("utf-8"))
    assert ok, msg
    assert mc.count("<import>") == 1
    assert "<parameterId>P.forecast</parameterId>" in mc


def test_all_instantaneous_selection_omits_empty_accumulated_block():
    # Mirror case: selecting ONLY instantaneous parameters must not emit an
    # empty Block 2 either.
    files = _render({"nwp_name": "GFS", "parameters": [
        {"id": "T.forecast", "unit": "K", "cumulativeSum": False,
         "gribVar": "TMP", "gribLevel": "2_m_above_ground",
         "external": "Temperature_height_above_ground"},
    ]})
    mc = files["ModuleConfigFiles/Import/NOAA/ImportGFS.xml"]
    ok, msg = validate_xsd(mc.encode("utf-8"))
    assert ok, msg
    assert mc.count("<import>") == 1
    assert "<parameterId>T.forecast</parameterId>" in mc


def test_default_parameters_all_nine():
    mc = _render()["ModuleConfigFiles/Import/NOAA/ImportGFS.xml"]
    assert mc.count("<timeSeriesSet>") == 9
    assert mc.count("<externUnit ") == 9
    assert mc.count('cumulativeSum="true"') == 3
    for pid in ("Pressure.msl", "Wind.u", "Wind.v", "T.forecast",
                "Tdew.forecast", "Cloudiness.forecast", "P.forecast",
                "Rs.forecast", "Rnl.forecast"):
        assert f"<parameterId>{pid}</parameterId>" in mc


def test_wind_uv_are_raw_no_derived_speed_direction():
    mc = _render()["ModuleConfigFiles/Import/NOAA/ImportGFS.xml"]
    assert "<parameterId>Wind.u</parameterId>" in mc
    assert "<parameterId>Wind.v</parameterId>" in mc
    assert "Wind.speed.forecast" not in mc
    assert "Wind.dir.forecast" not in mc
    files = _render()
    assert not any(
        "Wind.speed.forecast" in c or "Wind.dir.forecast" in c
        for c in files.values()
    )


def test_idmap_maps_all_nine_grib_names():
    idmap = _render()["IdMapFiles/Import/NOAA/IdImportGFSExtended.xml"]
    ok, msg = validate_xsd(idmap.encode("utf-8"))
    assert ok, msg
    expected = {
        "Pressure.msl": "Pressure_reduced_to_MSL_msl",
        "Wind.u": "u-component_of_wind_height_above_ground",
        "Wind.v": "v-component_of_wind_height_above_ground",
        "T.forecast": "Temperature_height_above_ground",
        "Tdew.forecast": "Dewpoint_temperature_height_above_ground",
        "Cloudiness.forecast": "Total_cloud_cover_entire_atmosphere",
        "P.forecast": "Total precipitation",
        "Rs.forecast": "Downward Short-Wave Radiation Flux",
        "Rnl.forecast": "Downward Long-Wave Rad. Flux",
    }
    for internal, external in expected.items():
        assert f'internal="{internal}" external="{external}"' in idmap


def test_workflow_single_activity():
    wf = _render()["WorkflowFiles/Import/NOAA/ImportGFSGrids.xml"]
    ok, msg = validate_xsd(wf.encode("utf-8"))
    assert ok, msg
    assert wf.count("<activity>") == 1
    assert "<moduleInstanceId>ImportGFS</moduleInstanceId>" in wf


def test_grid_resolution_parameterizes_url():
    mc = _render({"nwp_name": "GFS", "grid_resolution": "0p50"})[
        "ModuleConfigFiles/Import/NOAA/ImportGFS.xml"
    ]
    assert "filter_gfs_0p50.pl" in mc
    assert "pgrb2.0p50.f" in mc


def test_forecast_horizon_parameterizes_counter_upper_bound():
    mc = _render({"nwp_name": "GFS", "forecast_horizon_hours": 168})[
        "ModuleConfigFiles/Import/NOAA/ImportGFS.xml"
    ]
    assert "%COUNTER(000-168-3)%" in mc
    assert "%COUNTER(003-168-3)%" in mc


def _vocab():
    catalog = build_pattern_catalog(PATTERNS_ROOT)
    return _pattern_vocabularies(catalog)[PATTERN]


def test_data_types_precipitation_and_cloudiness():
    rows, unrecognised = _data_types_to_parameter_rows(
        ["precipitation", "cloudiness"], _vocab(),
    )
    assert not unrecognised
    assert {r["id"] for r in rows} == {"P.forecast", "Cloudiness.forecast"}


def test_wind_phrase_emits_two_rows():
    rows, unrecognised = _data_types_to_parameter_rows(["wind"], _vocab())
    assert not unrecognised
    assert {r["id"] for r in rows} == {"Wind.u", "Wind.v"}


def test_unrecognised_phrase_is_reported():
    rows, unrecognised = _data_types_to_parameter_rows(
        ["wind speed"], _vocab(),
    )
    # "wind speed" (direct speed) isn't in this pattern's vocabulary — GFS
    # doesn't serve it directly, only "wind"/"wind u component" etc.
    assert not rows
    assert unrecognised == ["wind speed"]
