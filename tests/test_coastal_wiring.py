"""Coastal-model chat wiring: domain skill + adapter map + resolver.

Pure-function tests (no LLM, no Ollama/Azure). They pin the wiring that lets
a SFINCS / HurryWave / Delft3D-FM request resolve its coastal pattern:

  * ``detect_coastal_domain`` extracts the domain independent of the region
    gazetteer (Caribbean is a region AND a valid domain name),
  * ``extract_skills`` feeds that domain into ``basin_name`` only when the
    adapter is coastal,
  * ``_resolve_basin_pattern`` maps each coastal adapter to its pattern with
    the right variable key (``domain`` / ``model_name``), leaving the
    hydrological adapters on ``basin_name``.
"""
from __future__ import annotations

import pytest

from fews_agent.agent import project_intents as pi


@pytest.mark.parametrize(
    "text, expected",
    [
        ("HurryWave coastal model for the Caribbean domain", "Caribbean"),
        ("sfincs model for the NorthAtlantic domain", "NorthAtlantic"),
        ("nest a sfincs run in the Saba domain", "Saba"),
        ("run hurrywave for North Atlantic", "NorthAtlantic"),
        ("import GFS grids for the basin", None),  # no coastal cue
    ],
)
def test_detect_coastal_domain(text, expected):
    assert pi.detect_coastal_domain(text) == expected


def test_extract_skills_feeds_domain_into_basin_name_for_coastal():
    sk = pi.extract_skills("Run a HurryWave model for the Caribbean domain")
    assert sk["model_adapter"] == "hurrywave"
    assert sk["coastal_domain"] == "Caribbean"
    # The domain is promoted into basin_name so the shared basin resolver fires.
    assert sk["basin_name"] == "Caribbean"


def test_extract_skills_does_not_hijack_basin_name_for_hydro():
    # A hydrological adapter must NOT pick up a coastal domain slot.
    sk = pi.extract_skills("Liard basin using raven")
    assert sk["model_adapter"] == "raven"
    assert sk["coastal_domain"] is None


@pytest.mark.parametrize(
    "adapter, name, expected_path, expected_var",
    [
        ("sfincs", "NorthAtlantic", "auto/coastal_sfincs", "domain"),
        ("hurrywave", "Caribbean", "auto/coastal_hurrywave", "domain"),
        ("delft3d", "Scheldt", "auto/coastal_dflowfm_dimr", "model_name"),
        ("raven", "Liard", "auto/raven_basin", "basin_name"),
    ],
)
def test_resolve_basin_pattern_uses_right_var_key(
    adapter, name, expected_path, expected_var
):
    paths = {expected_path}
    out = pi._resolve_basin_pattern(adapter, name, paths)
    assert out == [{"pattern": expected_path, "instances": [{expected_var: name}]}]


def test_resolve_basin_pattern_empty_without_name():
    assert pi._resolve_basin_pattern("sfincs", None, {"auto/coastal_sfincs"}) == []


# --- adapter-type-aware forecasting shared templates -----------------------

_ALL_PATHS = (
    set(pi._FORECASTING_SHARED_TEMPLATES)
    | set(pi._COASTAL_FORECASTING_TEMPLATES)
    | {"auto/raven_basin", "auto/coastal_hurrywave", "auto/nwp_grid_ecmwf_ifs"}
)


def _resolved_names(slots):
    return {r["pattern"] for r in pi._resolve_forecasting_patterns(slots, _ALL_PATHS)}


def test_hydro_forecast_gets_raven_templates_not_coastal():
    got = _resolved_names(
        {"basins": [{"basin_name": "Liard", "model_adapter": "raven"}], "imports": []}
    )
    assert "auto/tpl_preprocess_nwp_raven" in got       # hydro chain present
    assert not (got & set(pi._COASTAL_FORECASTING_TEMPLATES))  # no coastal leak


def test_coastal_forecast_gets_coastal_templates_not_raven():
    got = _resolved_names(
        {"basins": [{"basin_name": "Caribbean", "model_adapter": "hurrywave"}],
         "imports": ["ECMWF"]}
    )
    assert "auto/coastal_hurrywave" in got
    assert "auto/nwp_grid_ecmwf_ifs" in got
    assert set(pi._COASTAL_FORECASTING_TEMPLATES) <= got   # coastal chain present
    assert not (got & set(pi._FORECASTING_SHARED_TEMPLATES))  # no raven leak


def test_mixed_forecast_gets_both_template_sets():
    got = _resolved_names(
        {"basins": [
            {"basin_name": "Liard", "model_adapter": "raven"},
            {"basin_name": "Caribbean", "model_adapter": "hurrywave"},
        ], "imports": []}
    )
    assert set(pi._FORECASTING_SHARED_TEMPLATES) <= got
    assert set(pi._COASTAL_FORECASTING_TEMPLATES) <= got
