"""Slice D: end-to-end verification of the import -> interpolate path.

Builds a real project (NOAA GFS import + grid->station interpolation +
a locations.csv) through the full ``build_from_blueprint`` pipeline and
asserts:

  * every rendered XML is XSD-valid;
  * the interpolation's cross-file references actually resolve (grid input
    -> the ImportGFS module instance; station output -> a populated
    LocationSet -> the CSV-declared locations) — the semantic wiring, not
    just per-file schema validity;
  * the loud-failure guard fires when no ``locations.csv`` is provided.

This is the committable oracle for the interpolation leg (the on-disk
``projects/`` fixtures are gitignored, so a test is the durable guard).
"""
from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml
from rich.console import Console

from runners.agent.build_from_blueprint import build_from_blueprint

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "patterns"
NS = {"f": "http://www.wldelft.nl/fews"}

# Full NOAA param rows (the resolver supplies units; the pattern reads them).
_NOAA_PARAMS = [
    {"id": "PC.nwp", "unit": "mm", "cumulativeSum": True, "startTimeShiftHours": -3},
    {"id": "TA.nwp", "unit": "K"},
]

_STATIONS = [("ACCRA", 5.55, -0.20), ("LAGOS", 6.45, 3.40), ("ABIDJAN", 5.32, -4.02)]


def _build(tmp_path, *, with_locations=True, station_set="GuineaStations"):
    proj = tmp_path / "proj"
    (proj / "inputs").mkdir(parents=True)
    bp = {
        "name": "interp-e2e",
        "output_root": "out",
        "patterns": [
            {"pattern": "auto/nwp_grid_noaa", "instances": [
                {"nwp_name": "GFS", "parameters": _NOAA_PARAMS,
                 "contribute_parameters": True}]},
            {"pattern": "auto/wf_interpolate_nwp_to_stations", "instances": [
                {"nwp_name": "GFS", "parameters": _NOAA_PARAMS,
                 "station_locationset_id": station_set, "geo_datum": "WGS 1984"}]},
        ],
    }
    (proj / "project.yaml").write_text(yaml.safe_dump(bp), encoding="utf-8")
    inputs_dir = proj / "inputs"
    if with_locations:
        rows = "id,name,lat,lon\n" + "".join(
            f"{i},{i.title()},{lat},{lon}\n" for i, lat, lon in _STATIONS
        )
        (inputs_dir / "locations.csv").write_text(rows, encoding="utf-8")
    summary = build_from_blueprint(
        blueprint_path=proj / "project.yaml",
        pattern_root=PATTERNS_ROOT,
        inputs_dir=inputs_dir,
        console=Console(quiet=True),
    )
    return summary, proj / "out"


def _find(out_dir, suffix):
    for p in out_dir.rglob("*.xml"):
        if p.as_posix().endswith(suffix):
            return p
    raise AssertionError(f"no rendered file ending in {suffix}")


def test_full_build_all_xsd_valid(tmp_path):
    summary, _ = _build(tmp_path)
    assert summary["ok"], summary.get("errors")
    assert summary["files_xsd_ok"] == summary["files_xml"]
    # The healthy case: nothing left unbacked.
    assert summary["unbacked_interpolation_sets"] == []


def test_station_set_membership_resolves_to_locations(tmp_path):
    # Semantic wiring: every <locationId> in the interpolation's station
    # set must be a real <location id> declared in Locations.xml.
    _, out = _build(tmp_path)
    locsets = ET.parse(_find(out, "RegionConfigFiles/LocationSets.xml")).getroot()
    guinea = next(
        ls for ls in locsets.findall("f:locationSet", NS)
        if ls.get("id") == "GuineaStations"
    )
    members = [e.text for e in guinea.findall("f:locationId", NS)]
    assert members == ["ACCRA", "LAGOS", "ABIDJAN"]

    locations = ET.parse(_find(out, "RegionConfigFiles/Locations.xml")).getroot()
    declared = {loc.get("id") for loc in locations.findall("f:location", NS)}
    assert set(members) <= declared


def test_interpolation_input_resolves_to_import_module(tmp_path):
    # The grid input must point at the ImportGFS instance, and that module
    # must actually exist in the rendered tree.
    _, out = _build(tmp_path)
    module = ET.parse(_find(out, "InterpolateGFSToStations.xml")).getroot()
    grid_tss = next(
        v.find("f:timeSeriesSet", NS)
        for v in module.findall("f:variable", NS)
        if (v.findtext("f:variableId", namespaces=NS) or "").startswith("Grid_")
    )
    assert grid_tss.findtext("f:moduleInstanceId", namespaces=NS) == "ImportGFS"
    # ImportGFS module config is in the tree (the instance is declared).
    assert any(
        p.as_posix().endswith("ImportGFS.xml") for p in out.rglob("*.xml")
    )


def test_interpolation_output_targets_the_station_set(tmp_path):
    _, out = _build(tmp_path, station_set="GuineaStations")
    module = ET.parse(_find(out, "InterpolateGFSToStations.xml")).getroot()
    station_tss = next(
        v.find("f:timeSeriesSet", NS)
        for v in module.findall("f:variable", NS)
        if (v.findtext("f:variableId", namespaces=NS) or "").startswith("Station_")
    )
    assert station_tss.findtext("f:locationSetId", namespaces=NS) == "GuineaStations"


def test_loud_failure_when_no_locations_csv(tmp_path):
    # Without locations.csv the station set is an unbacked stub: the build
    # still succeeds (XSD-valid) but loudly flags the inert interpolation.
    summary, out = _build(tmp_path, with_locations=False)
    assert summary["ok"], summary.get("errors")
    assert "GuineaStations" in summary["unbacked_interpolation_sets"]
    # And the set really is a bare stub in the rendered XML.
    locsets = ET.parse(_find(out, "RegionConfigFiles/LocationSets.xml")).getroot()
    guinea = next(
        ls for ls in locsets.findall("f:locationSet", NS)
        if ls.get("id") == "GuineaStations"
    )
    assert list(guinea) == []  # no children = unbacked
