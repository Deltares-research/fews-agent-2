"""archive_export_netcdf — the first archive/export pattern in the library.

Farmed from FEWS-Conform (ToArchiveGFS.xml + ToArchiveObserved.xml), it is
one template-family covering the gridded external-forecast export and the
scalar observed export. These tests render both variants through the real
expand() path and XSD-validate the ExportArchiveModule + Workflow outputs,
and assert the rendered XML reproduces the Conform source's key content.
"""
from __future__ import annotations

from pathlib import Path

from fews_agent.agent.blueprint import Blueprint, PatternRef, expand
from fews_agent.validation.xsd import validate_xsd

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "patterns"
PATTERN = "auto/archive_export_netcdf"

FORECAST = {
    "name": "Gfs",
    "export_kind": "exportExternalForecast",
    "source_module_instance": "ImportGfs",
    "value_type": "grid",
    "parameters": ["Precipitation", "AirTemperature", "WindSpeedU", "WindSpeedV"],
    "nc_filename": "GfsDET.nc",
    "area_id": "FewsConform",
    "source_id": "GFS",
    "location_id": "Gfs",
    "period_unit": "hour", "period_start": "-48", "period_end": "0",
    "time_step_unit": "hour", "time_step_multiplier": "1",
}

OBSERVED = {
    "name": "Observed",
    "export_kind": "exportObserved",
    "source_module_instance": "ImportGhcnd",
    "value_type": "scalar",
    "parameters": ["PrecipitationObserved"],
    "nc_filename": "PrecipitationObservedHour.nc",
    "area_id": "Local",
    "location_set_id": "Stations",
    "archive_folder": r"$FromFewsFolder$\Archive",
    "period_unit": "day", "period_start": "-5", "period_end": "0",
    "time_step_unit": "day",
    "nc_title": "Observed Precipitation",
    "nc_institution": "Deltares",
    "nc_source": "Delft-FEWS (Conform)",
    "include_comments": True, "include_flags": True,
    "threshold_group_id": "ThresholdsH",
}


def _render(*instances):
    bp = Blueprint(
        name="archive-test", output_root=Path("out"),
        patterns=[PatternRef(pattern=PATTERN, instances=list(instances))],
    )
    res = expand(bp, PATTERNS_ROOT)
    assert not res.errors, res.errors
    return {rf.relpath.replace("\\", "/"): rf.content for rf in res.rendered_files}


def _xsd_ok(xml):
    ok, msg = validate_xsd(xml.encode("utf-8"))
    assert ok, msg


def test_forecast_export_renders_and_validates():
    files = _render(FORECAST)
    mc = files["ModuleConfigFiles/Archive/ToArchiveGfs.xml"]
    wf = files["WorkflowFiles/Archive/To_Archive_Gfs.xml"]
    _xsd_ok(mc)
    _xsd_ok(wf)
    # Reproduces the Conform forecast-export shape.
    assert "<exportExternalForecast>" in mc
    assert "<sourceId>GFS</sourceId>" in mc
    assert '<relativePeriod unit="hour" start="-48" end="0"/>' in mc
    assert mc.count("<timeSeriesSet>") == 4          # one per parameter
    assert "<locationId>Gfs</locationId>" in mc
    assert "<timeSeriesType>external forecasting</timeSeriesType>" in mc
    assert "<readWriteMode>read complete forecast</readWriteMode>" in mc
    # Workflow runs the module instance named after the export.
    assert "<moduleInstanceId>ToArchiveGfs</moduleInstanceId>" in wf


def test_observed_export_renders_and_validates():
    mc = _render(OBSERVED)["ModuleConfigFiles/Archive/ToArchiveObserved.xml"]
    _xsd_ok(mc)
    assert "<exportObserved>" in mc
    assert "<sourceId>" not in mc                     # observed carries no sourceId
    assert "<ncMetaData>" in mc
    assert "<institution>Deltares</institution>" in mc
    assert "<includeFlags>true</includeFlags>" in mc
    assert "<thresholdGroupId>ThresholdsH</thresholdGroupId>" in mc
    assert "<locationSetId>Stations</locationSetId>" in mc
    assert "<timeSeriesType>external historical</timeSeriesType>" in mc
    assert "<readWriteMode>read only</readWriteMode>" in mc


def test_derived_defaults_switch_on_export_kind():
    # No explicit time_series_type/read_write_mode → derived from kind.
    fc = _render(FORECAST)["ModuleConfigFiles/Archive/ToArchiveGfs.xml"]
    ob = _render(OBSERVED)["ModuleConfigFiles/Archive/ToArchiveObserved.xml"]
    assert "external forecasting" in fc and "read complete forecast" in fc
    assert "external historical" in ob and "read only" in ob


def test_forecast_export_defaults_source_id_to_name():
    # exportExternalForecast REQUIRES <sourceId> (XSD). Omitting source_id
    # must NOT render invalid — it defaults to the export name.
    inst = dict(FORECAST)
    inst.pop("source_id")
    mc = _render(inst)["ModuleConfigFiles/Archive/ToArchiveGfs.xml"]
    _xsd_ok(mc)
    assert "<sourceId>Gfs</sourceId>" in mc            # defaulted to name


def test_emits_resolvable_idmap():
    # The exportArchiveModule references idMapId=IdMapToArchive; the pattern
    # emits a matching 1:1 idMap so the reference resolves out of the box.
    files = _render(FORECAST)
    idm = files["IdMapFiles/Archive/IdMapToArchive.xml"]
    _xsd_ok(idm)
    assert '<parameter internal="Precipitation" external="Precipitation"/>' in idm
    assert "<enableOneToOneMapping/>" in idm
