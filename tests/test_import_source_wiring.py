"""Chat wiring for the FEWS-Caribbean import sources.

Pure-function tests (no LLM). Pin that ECMWF / GHCN-D / JTWC / IOC / NDBC are
detected in prose and resolve to their farmed patterns with the patterns'
title-case ``source_name`` default (Ecmwf, Ghcnd, ...), not the upper-case
detection token.
"""
from __future__ import annotations

import pytest

from fews_agent.agent import project_intents as pi


def test_detect_imports_finds_caribbean_sources():
    got = set(pi.detect_imports(
        "Import ECMWF IFS, GHCN-D stations, NDBC buoys, IOC sea level, JTWC tracks"
    ))
    assert {"ECMWF", "GHCND", "NDBC", "IOC", "JTWC"} <= got


@pytest.mark.parametrize(
    "alias_text, canonical",
    [("pull the IFS grids", "ECMWF"), ("GHCN daily data", "GHCND")],
)
def test_import_aliases(alias_text, canonical):
    assert canonical in pi.detect_imports(alias_text)


@pytest.mark.parametrize(
    "imp, path, source_name",
    [
        ("ECMWF", "auto/nwp_grid_ecmwf_ifs", "Ecmwf"),
        ("GHCND", "auto/import_station_ghcnd", "Ghcnd"),
        ("JTWC", "auto/import_cyclone_jtwc", "Jtwc"),
        ("IOC", "auto/import_sealevel_ioc", "Ioc"),
        ("NDBC", "auto/import_buoy_ndbc", "Ndbc"),
    ],
)
def test_import_resolves_to_pattern_with_titlecase_name(imp, path, source_name):
    out = pi._resolve_import_patterns([imp], {path})
    assert out == [{"pattern": path, "instances": [{"source_name": source_name}]}]


def _station_note(imports):
    status = pi.compute_input_status(
        "build_data_import_only", {"csvs": [], "yamls": []}, {"imports": imports}
    )
    return [n for n in status["extra_notes"] if "Station imports" in n]


@pytest.mark.parametrize("imports", [["NDBC"], ["IOC"], ["GHCND"], ["NDBC", "IOC"]])
def test_station_sources_get_locations_csv_reminder(imports):
    assert _station_note(imports), imports


@pytest.mark.parametrize("imports", [["ECMWF"], ["GFS"], []])
def test_non_station_sources_no_reminder(imports):
    assert not _station_note(imports)
