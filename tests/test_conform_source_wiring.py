"""Chat wiring for the FEWS-Conform import families.

Pure-function tests (no LLM). Pin that ERA5 / GEFS / IMERG are detected in
prose and resolve to their farmed patterns with the PascalCase source_name,
and that selecting ERA5 also pulls in its download_via_python_venv companion.
"""
from __future__ import annotations

import pytest

from fews_agent.agent import project_intents as pi
from fews_agent.agent.phases import classify_phase

CATALOG = {
    "auto/import_era5", "auto/download_via_python_venv",
    "auto/nwp_grid_noaa_gefs", "auto/import_imerg",
}


def test_detect_conform_sources():
    got = set(pi.detect_imports(
        "import ERA5 reanalysis, a GEFS ensemble, and IMERG precipitation"
    ))
    assert {"ERA5", "GEFS", "IMERG"} <= got


def test_era5_hyphen_alias():
    assert "ERA5" in pi.detect_imports("pull the ERA-5 grids")


@pytest.mark.parametrize(
    "imp, path, source_name",
    [
        ("ERA5", "auto/import_era5", "Era5"),
        ("GEFS", "auto/nwp_grid_noaa_gefs", "Gefs"),
        ("IMERG", "auto/import_imerg", "Imerg"),
    ],
)
def test_resolves_with_pascalcase_source_name(imp, path, source_name):
    out = pi._resolve_import_patterns([imp], CATALOG)
    inst = next(r for r in out if r["pattern"] == path)["instances"]
    assert inst == [{"source_name": source_name}]


def test_era5_pulls_download_companion():
    out = pi._resolve_import_patterns(["ERA5"], CATALOG)
    paths = {r["pattern"] for r in out}
    assert paths == {"auto/import_era5", "auto/download_via_python_venv"}
    dl = next(r for r in out if r["pattern"] == "auto/download_via_python_venv")
    inst = dl["instances"][0]
    assert inst["source_name"] == "Era5"
    assert inst["import_module_instance"] == "ImportEra5"
    assert inst["download_area"] and inst["download_parameters"]


def test_download_companion_only_when_pattern_in_catalog():
    # Without the download pattern in the catalog, ERA5 still resolves the
    # import alone (no crash, no phantom pattern).
    out = pi._resolve_import_patterns(["ERA5"], {"auto/import_era5"})
    assert {r["pattern"] for r in out} == {"auto/import_era5"}


@pytest.mark.parametrize("path", sorted(CATALOG))
def test_conform_imports_classify_into_imports_phase(path):
    assert classify_phase(path) == "imports"
