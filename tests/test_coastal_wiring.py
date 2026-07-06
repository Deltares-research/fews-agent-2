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
