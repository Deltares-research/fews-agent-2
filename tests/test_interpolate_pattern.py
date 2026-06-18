"""Slice A tests: the grid->station interpolation pattern.

`patterns/auto/wf_interpolate_nwp_to_stations` emits a self-contained
spatial-interpolation transformation module (one grid->station pair per
parameter) plus the workflow that runs it. Unlike the basin postprocess
template, the gridded input is read from the upstream ``Import<nwp>``
module instance, so it works in a no-basin import-only project.

These tests render the pattern through the real build_module path and
assert (a) both outputs XSD-validate and (b) the cross-module wiring is
correct (grid in from Import<nwp>, station out to the target locationSet).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from runners.agent.build_from_blueprint import build_module

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "patterns"
PATTERN = "auto/wf_interpolate_nwp_to_stations"
NS = {"f": "http://www.wldelft.nl/fews"}


def _render(tmp_path, nwp_name="GFS", parameters=None, extra=None):
    """Render one pattern instance; return (summary, output_dir)."""
    inst = {"nwp_name": nwp_name}
    if parameters is not None:
        inst["parameters"] = parameters
    if extra:
        inst.update(extra)
    import yaml

    bp = {
        "name": "interp-test",
        "output_root": "out",
        "patterns": [{"pattern": PATTERN, "instances": [inst]}],
    }
    bp_path = tmp_path / "project.yaml"
    bp_path.write_text(yaml.safe_dump(bp), encoding="utf-8")
    summary = build_module(
        blueprint_path=bp_path, pattern_root=PATTERNS_ROOT, pattern=PATTERN,
    )
    return summary, tmp_path / "out"


def _module_xml(out_dir, nwp_name="GFS"):
    p = out_dir / "ModuleConfigFiles" / "Interpolate" / f"Interpolate{nwp_name}ToStations.xml"
    return ET.parse(p).getroot()


def _workflow_xml(out_dir, nwp_name="GFS"):
    p = out_dir / "WorkflowFiles" / "Interpolate" / f"Interpolate{nwp_name}ToStations.xml"
    return ET.parse(p).getroot()


def test_renders_and_xsd_valid(tmp_path):
    summary, _ = _render(tmp_path)
    assert summary["ok"], summary
    assert summary["files_total"] == 2
    assert summary["files_xsd_ok"] == summary["files_xml"] == 2


def test_one_transform_and_two_variables_per_parameter(tmp_path):
    _, out = _render(
        tmp_path, parameters=[{"id": "PC.nwp"}, {"id": "TA.nwp"}, {"id": "WS10.nwp"}],
    )
    root = _module_xml(out)
    variables = root.findall("f:variable", NS)
    transforms = root.findall("f:transformation", NS)
    assert len(variables) == 6   # 2 (grid + station) per parameter
    assert len(transforms) == 3  # 1 interpolation per parameter


def test_grid_input_reads_from_upstream_import(tmp_path):
    # The defining property of this pattern: the gridded input comes from
    # Import<nwp>, NOT from the interpolation module's own instance.
    _, out = _render(tmp_path, nwp_name="GFS", parameters=[{"id": "PC.nwp"}])
    root = _module_xml(out)
    grid_var = next(
        v for v in root.findall("f:variable", NS)
        if v.findtext("f:variableId", namespaces=NS) == "Grid_PC_nwp"
    )
    tss = grid_var.find("f:timeSeriesSet", NS)
    assert tss.findtext("f:moduleInstanceId", namespaces=NS) == "ImportGFS"
    assert tss.findtext("f:valueType", namespaces=NS) == "grid"
    assert tss.findtext("f:locationId", namespaces=NS) == "GFS"


def test_station_output_targets_locationset(tmp_path):
    _, out = _render(
        tmp_path, parameters=[{"id": "PC.nwp"}],
        extra={"station_locationset_id": "GuineaStations"},
    )
    root = _module_xml(out)
    station_var = next(
        v for v in root.findall("f:variable", NS)
        if v.findtext("f:variableId", namespaces=NS) == "Station_PC_nwp"
    )
    tss = station_var.find("f:timeSeriesSet", NS)
    assert tss.findtext("f:moduleInstanceId", namespaces=NS) == "InterpolateGFSToStations"
    assert tss.findtext("f:valueType", namespaces=NS) == "scalar"
    assert tss.findtext("f:locationSetId", namespaces=NS) == "GuineaStations"


def test_workflow_runs_the_module(tmp_path):
    _, out = _render(tmp_path)
    wf = _workflow_xml(out)
    activities = wf.findall("f:activity", NS)
    assert len(activities) == 1
    act = activities[0]
    assert act.findtext("f:moduleInstanceId", namespaces=NS) == "InterpolateGFSToStations"
    assert act.findtext("f:moduleConfigFileName", namespaces=NS) == "InterpolateGFSToStations"


def test_closestdistance_transform_links_grid_to_station(tmp_path):
    _, out = _render(tmp_path, parameters=[{"id": "PC.nwp"}])
    root = _module_xml(out)
    t = root.find("f:transformation", NS)
    cd = t.find("f:interpolationSpatial/f:closestDistance", NS)
    assert cd is not None
    assert cd.findtext("f:inputVariable/f:variableId", namespaces=NS) == "Grid_PC_nwp"
    assert cd.findtext("f:outputVariable/f:variableId", namespaces=NS) == "Station_PC_nwp"


@pytest.mark.parametrize("nwp", ["GFS", "HRDPS"])
def test_filenames_scoped_to_nwp(tmp_path, nwp):
    summary, out = _render(tmp_path, nwp_name=nwp)
    assert summary["ok"]
    assert (out / "ModuleConfigFiles" / "Interpolate" / f"Interpolate{nwp}ToStations.xml").exists()
    assert (out / "WorkflowFiles" / "Interpolate" / f"Interpolate{nwp}ToStations.xml").exists()


# --- Slice C: resolver wiring -------------------------------------------
# The chat resolver, when wants_interpolation is set, should emit the new
# self-contained interpolation pattern (and ONLY it — not the inert basin
# postprocess template that used to be force-fitted onto the import path).

from fews_agent.agent.phases import classify_phase
from fews_agent.agent.project_intents import (
    _resolve_data_import_only_patterns,
    _resolve_forecasting_patterns,
)

_INTERP_CATALOG = {
    "auto/nwp_grid_noaa", "auto/nwp_grid_eccc_HRDPS", "auto/wf_import_noaa_grids",
    "auto/wf_interpolate_nwp_to_stations", "auto/tpl_postprocess_to_station",
    "auto/spatial_display_grid", "auto/raven_basin",
}


def _patterns(resolved):
    return [p["pattern"] for p in resolved]


def test_import_interpolation_emits_only_the_workflow_pattern():
    # Data-import-only path must NOT carry the basin postprocess template.
    slots = {
        "imports": ["GFS"],
        "data_types": ["precipitation", "temperature"],
        "wants_interpolation": True,
    }
    paths = _patterns(_resolve_data_import_only_patterns(slots, _INTERP_CATALOG))
    assert "auto/wf_interpolate_nwp_to_stations" in paths
    assert "auto/tpl_postprocess_to_station" not in paths


def test_interpolation_plumbs_geo_datum():
    slots = {
        "imports": ["GFS"],
        "data_types": ["precipitation"],
        "wants_interpolation": True,
        "geoDatum": "Ordnance Survey of Great Britain 1936",
    }
    resolved = _resolve_data_import_only_patterns(slots, _INTERP_CATALOG)
    inst = next(
        p for p in resolved if p["pattern"] == "auto/wf_interpolate_nwp_to_stations"
    )["instances"][0]
    assert inst["geo_datum"] == "Ordnance Survey of Great Britain 1936"


def test_no_geo_datum_slot_leaves_pattern_default():
    slots = {
        "imports": ["GFS"], "data_types": ["precipitation"],
        "wants_interpolation": True,
    }
    resolved = _resolve_data_import_only_patterns(slots, _INTERP_CATALOG)
    inst = next(
        p for p in resolved if p["pattern"] == "auto/wf_interpolate_nwp_to_stations"
    )["instances"][0]
    assert "geo_datum" not in inst  # pattern.yaml default applies


def _interp_instances(resolved):
    return next(
        p for p in resolved
        if p["pattern"] == "auto/wf_interpolate_nwp_to_stations"
    )["instances"]


def test_eccc_hrdps_interpolates_with_its_timestep():
    # HRDPS is now interpolatable; it imports PC.nwp/TA.nwp at a 1-hour
    # step, so the interpolation must read at multiplier 1 (not the 3-hour
    # default) or the grid input won't match the import at runtime.
    slots = {
        "imports": ["HRDPS"], "data_types": ["precipitation", "temperature"],
        "wants_interpolation": True,
    }
    insts = _interp_instances(_resolve_data_import_only_patterns(slots, _INTERP_CATALOG))
    assert len(insts) == 1
    assert insts[0]["nwp_name"] == "HRDPS"
    assert insts[0]["time_step_hours"] == 1
    ids = {r["id"] for r in insts[0]["parameters"]}
    assert ids == {"PC.nwp", "TA.nwp"}


def test_eccc_intersects_requested_params_with_import_set():
    # HRDPS imports only PC.nwp/TA.nwp — a requested wind-speed param it
    # doesn't carry must be dropped, not referenced un-imported.
    slots = {
        "imports": ["HRDPS"],
        "data_types": ["precipitation", "wind speed"],
        "wants_interpolation": True,
    }
    insts = _interp_instances(_resolve_data_import_only_patterns(slots, _INTERP_CATALOG))
    ids = {r["id"] for r in insts[0]["parameters"]}
    assert ids == {"PC.nwp"}  # WS10.nwp dropped — HRDPS doesn't import it


def test_eccc_with_no_importable_param_is_skipped():
    # Asking to interpolate only wind speed from HRDPS yields nothing to
    # interpolate (empty intersection) — no instance emitted.
    slots = {
        "imports": ["HRDPS"], "data_types": ["wind speed"],
        "wants_interpolation": True,
    }
    paths = _patterns(_resolve_data_import_only_patterns(slots, _INTERP_CATALOG))
    assert "auto/wf_interpolate_nwp_to_stations" not in paths


def test_reps_ensemble_grid_is_excluded():
    # REPS is an ensemble grid — not interpolatable until we emit
    # ensemble-aware interpolation.
    cat = _INTERP_CATALOG | {"auto/nwp_grid_eccc_REPS"}
    slots = {
        "imports": ["REPS"], "data_types": ["precipitation"],
        "wants_interpolation": True,
    }
    paths = _patterns(_resolve_data_import_only_patterns(slots, cat))
    assert "auto/wf_interpolate_nwp_to_stations" not in paths


def test_mixed_imports_each_get_own_param_and_timestep():
    # GFS (parameterized, 3h) + HRDPS (fixed set, 1h) interpolated together,
    # each correctly scoped.
    cat = _INTERP_CATALOG
    slots = {
        "imports": ["GFS", "HRDPS"],
        "data_types": ["precipitation", "temperature", "wind speed"],
        "wants_interpolation": True,
    }
    insts = {
        i["nwp_name"]: i
        for i in _interp_instances(_resolve_data_import_only_patterns(slots, cat))
    }
    assert insts["GFS"]["time_step_hours"] == 3
    assert {r["id"] for r in insts["GFS"]["parameters"]} == {
        "PC.nwp", "TA.nwp", "WS10.nwp"
    }
    assert insts["HRDPS"]["time_step_hours"] == 1
    assert {r["id"] for r in insts["HRDPS"]["parameters"]} == {"PC.nwp", "TA.nwp"}


def test_forecasting_postprocess_is_not_dropped():
    # The basin postprocess template is a legitimate forecasting member
    # (via shared templates) and must survive the Slice C cleanup; it is
    # emitted once, alongside — not instead of — the import interpolation.
    slots = {
        "imports": ["GFS"], "data_types": ["precipitation"],
        "wants_interpolation": True,
        "basins": [{"basin_name": "Liard", "model_adapter": "raven"}],
    }
    paths = _patterns(_resolve_forecasting_patterns(slots, _INTERP_CATALOG))
    assert paths.count("auto/tpl_postprocess_to_station") == 1
    assert paths.count("auto/wf_interpolate_nwp_to_stations") == 1


def test_interpolate_pattern_classifies_as_process_phase():
    assert classify_phase("auto/wf_interpolate_nwp_to_stations") == "process"
