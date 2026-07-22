"""Reference projects per FEWS-Conform family assemble into a resolving config.

Tier-2 operational evidence: a farmed pattern that only XSD-validates in
isolation isn't necessarily usable. Each test builds a minimal but complete
project for a family (blueprint + parameters.csv + locations.csv) through the
FULL pipeline, then asserts — via scripts/check_references.analyze — that the
family's OWN cross-references resolve (the params it consumes, its grid
location, its idMap, and every module/locationSet it declares). A constant
floor of bundled-standard references (PC.nwp / TA.nwp / GDPS…) is expected
noise and is NOT asserted on.

Self-contained (inputs written to tmp_path) so it survives a fresh clone —
the persisted projects/conform-ref/ copies are gitignored, for inspection.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from runners.agent.build_from_blueprint import build_from_blueprint  # noqa: E402
from scripts.check_references import analyze  # noqa: E402

PATTERNS_ROOT = REPO_ROOT / "fews_agent" / "patterns"

_PARAMS = (
    "Category,ParameterId,ParameterName,ShortName,ParameterGroupId,"
    "ParameterGroupName,ParameterType,Unit,DisplayUnit,AllowMissing\n"
)


def _build(tmp_path, blueprint_yaml, params_rows, locations_rows):
    inp = tmp_path / "inputs"
    inp.mkdir()
    (inp / "parameters.csv").write_text(_PARAMS + params_rows, encoding="utf-8")
    (inp / "locations.csv").write_text(
        "FewsId,Name,Lat,Lon,Alt\n" + locations_rows, encoding="utf-8"
    )
    bp = tmp_path / "project.yaml"
    bp.write_text(blueprint_yaml, encoding="utf-8")
    summary = build_from_blueprint(
        blueprint_path=bp, pattern_root=PATTERNS_ROOT, inputs_dir=inp,
    )
    assert summary.get("ok") is not False, summary.get("errors")
    return analyze((bp.parent / "out").resolve())


def test_era5_family_references_resolve(tmp_path):
    bp = """
name: ref-era5
output_root: out
patterns:
  - pattern: auto/download_via_python_venv
    instances: [{source_name: Era5, import_module_instance: ImportEra5, download_area: '[0,0,1,1]', download_parameters: "['x']"}]
  - pattern: auto/import_era5
    instances: [{station_locationset: GhcndStations, catchment_locationset: GhcndStations}]
singleton_seeds: {Locations: {geoDatum: WGS 1984}}
"""
    res = _build(
        tmp_path, bp,
        "Meteo,AirTemperature,Air temp,T,Temperature,Temperature,instantaneous,K,degC,TRUE\n"
        "Meteo,RadiationSolar,Solar rad,R,Radiation,Radiation,instantaneous,Jm-2,Jm-2,TRUE\n"
        "Meteo,Precipitation,Precip,P,Precipitation,Precipitation,accumulative,m,mm,TRUE\n",
        "Era5,ERA5 grid,0,0,0\nStn1,Station,-28.4,151.2,0\n",
    )
    assert {"AirTemperature", "RadiationSolar", "Precipitation"} <= (
        res["parameterId"]["resolved"]
    )
    assert "Era5" in res["locationId"]["resolved"]
    assert "IdMapFromEra5" in res["idMapId"]["resolved"]
    # Everything the family declares must resolve (no dangling modules/sets/idmaps).
    assert res["moduleInstanceId"]["unresolved"] == set()
    assert res["locationSetId"]["unresolved"] == set()
    assert res["idMapId"]["unresolved"] == set()


def test_gefs_family_references_resolve(tmp_path):
    bp = """
name: ref-gefs
output_root: out
patterns:
  - pattern: auto/nwp_grid_noaa_gefs
    instances: [{}]
singleton_seeds: {Locations: {geoDatum: WGS 1984}}
"""
    res = _build(
        tmp_path, bp,
        "Meteo,Precipitation,Precip,P,Precipitation,Precipitation,accumulative,mm,mm,TRUE\n"
        "Meteo,AirTemperature,Air temp,T,Temperature,Temperature,instantaneous,K,degC,TRUE\n",
        "Gefs,GEFS grid,0,0,0\n",
    )
    assert {"Precipitation", "AirTemperature"} <= res["parameterId"]["resolved"]
    assert "Gefs" in res["locationId"]["resolved"]
    assert "IdMapFromGefs" in res["idMapId"]["resolved"]
    assert res["moduleInstanceId"]["unresolved"] == set()
    assert res["idMapId"]["unresolved"] == set()


def test_archive_family_references_resolve(tmp_path):
    # The fixed archive_export: forecast export defaults sourceId, and emits
    # IdMapToArchive so its idMapId reference resolves.
    bp = """
name: ref-archive
output_root: out
patterns:
  - pattern: auto/nwp_grid_noaa
    instances: [{nwp_name: GFS, parameters: [{id: Precipitation, unit: mm}]}]
  - pattern: auto/archive_export_netcdf
    instances:
      - {name: Gfs, export_kind: exportExternalForecast, source_module_instance: ImportGFS, value_type: grid, parameters: [Precipitation], nc_filename: GfsDET.nc, area_id: FewsConform, location_id: GFS, period_unit: hour, period_start: '-48', period_end: '0', time_step_unit: hour, time_step_multiplier: '1'}
  - pattern: auto/archive_import
    instances:
      - {name: Data, archive_root: $ArchiveDownloadFolder$, categories: [observed], id_map: IdMapFromGFS}
singleton_seeds: {Locations: {geoDatum: WGS 1984}}
"""
    res = _build(
        tmp_path, bp,
        "Meteo,Precipitation,Precip,P,Precipitation,Precipitation,accumulative,mm,mm,TRUE\n",
        "GFS,GFS grid,0,0,0\n",
    )
    # IdMapToArchive (export) + IdMapFromGFS (import) + IdImportGFS all resolve.
    assert res["idMapId"]["unresolved"] == set()
    assert "IdMapToArchive" in res["idMapId"]["resolved"]
    assert res["moduleInstanceId"]["unresolved"] == set()
