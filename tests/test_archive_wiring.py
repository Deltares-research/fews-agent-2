"""Chat wiring for the FEWS-Conform archive (Open Archive) capability.

Pure-function tests (no LLM). Archive is a composable slot (like
wants_maintenance): directional detectors feed wants_archive_export /
wants_archive_import, and _resolve_archive_patterns appends an
exportExternalForecast per forecast-grid import already in the project plus a
self-contained FromArchiveData reader.
"""
from __future__ import annotations

import pytest

from fews_agent.agent import project_intents as pi

CATALOG = {"auto/archive_export_netcdf", "auto/archive_import"}


@pytest.mark.parametrize(
    "text, export, imp",
    [
        ("archive my GFS forecasts", True, None),
        ("set up archiving", True, None),
        ("export forecasts to the archive", True, None),
        ("retrieve observations from the archive", None, True),
        ("import from archive", None, True),
        ("archive forecasts and read history from archive", True, True),
        ("import GFS grids", None, None),   # no archive intent
    ],
)
def test_archive_direction_detection(text, export, imp):
    assert pi.detect_wants_archive_export(text) is export
    assert pi.detect_wants_archive_import(text) is imp


def test_export_emits_one_per_forecast_grid_import():
    out = pi._resolve_archive_patterns(
        {"imports": ["GFS", "GEFS", "GHCND"], "wants_archive_export": True},
        CATALOG,
    )
    (entry,) = [r for r in out if r["pattern"] == "auto/archive_export_netcdf"]
    names = {i["name"] for i in entry["instances"]}
    assert names == {"GFS", "Gefs"}                  # GHCND (station) excluded
    gfs = next(i for i in entry["instances"] if i["name"] == "GFS")
    assert gfs["export_kind"] == "exportExternalForecast"
    assert gfs["source_module_instance"] == "ImportGFS"
    gefs = next(i for i in entry["instances"] if i["name"] == "Gefs")
    assert gefs["source_module_instance"] == "ImportGefs"


def test_export_without_any_forecast_import_emits_nothing():
    # "archive" with nothing to archive → no export instance.
    out = pi._resolve_archive_patterns(
        {"imports": ["GHCND"], "wants_archive_export": True}, CATALOG
    )
    assert out == []


def test_import_emits_self_contained_reader():
    out = pi._resolve_archive_patterns(
        {"imports": [], "wants_archive_import": True}, CATALOG
    )
    (entry,) = out
    assert entry["pattern"] == "auto/archive_import"
    inst = entry["instances"][0]
    assert inst["categories"] == ["simulated", "externalForecast", "observed"]
    assert "id_map" not in inst                       # no unresolved idMap ref


def test_no_archive_slot_no_patterns():
    assert pi._resolve_archive_patterns({"imports": ["GFS"]}, CATALOG) == []


def test_extract_skills_surfaces_archive_slots():
    sk = pi.extract_skills("archive the forecasts to the open archive")
    assert sk["wants_archive_export"] is True
    assert sk["wants_archive_import"] is None
