"""Capability reach: the pattern library resolves itself.

The three intent resolvers map imports / basins / visualisation / interpolation
onto patterns and fully REBUILD ``state["patterns"]`` every turn. Anything
outside those mappings used to be unreachable by conversation — worse, naming
it ("add SFINCS") was rejected by ``validate_fields`` as a hallucinated import,
while the pattern sat in the library rendering valid XML.

The fix is declarative, not a lookup table: each harvested ``pattern.yaml``
declares its own ``keywords`` (how a configurator refers to it) and its own
``variables`` (what it requires). Resolution reads THOSE, so harvesting a new
pattern with keywords makes it reachable with no Python change.

A pattern WITHOUT keywords is deliberately not directly nameable: ``tpl_*`` /
``wf_*`` fragments are attached by the resolvers as part of a larger
capability, and import/basin patterns are owned by routes that also fill their
required variables.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fews_agent.agent import modules as M
from fews_agent.agent import turn_engine as TE
from fews_agent.agent.blueprint import Blueprint, PatternRef, expand
from fews_agent.agent.extractor import deterministic_module_op
from fews_agent.agent.project_chat import build_pattern_catalog
from fews_agent.agent.project_intents import (
    _capability_entries,
    capability_required_variables,
    detect_capabilities,
    split_addable_capabilities,
)
from fews_agent.validation.xsd import validate_xsd

REPO = Path(__file__).resolve().parents[1]
PROC = M.get_module("processing")


@pytest.fixture(scope="module")
def catalog():
    return build_pattern_catalog(REPO / "fews_agent" / "patterns")


def _nameable(catalog):
    """Directly-nameable capabilities: declare keywords AND aren't owned by the
    import/basin/display routes (which fill their required variables)."""
    return _capability_entries(catalog)


# --- 1. basins are as deterministic as imports ----------------------------

@pytest.mark.parametrize("phrase,adapter", [
    ("Liard uses raven", "raven"),
    ("Liard uses wflow", "wflow"),
    ("Rhine uses hbv96", "hbv96"),
    ("add the Liard basin using raven", "raven"),
])
def test_basin_with_adapter_is_a_deterministic_add(phrase, adapter, catalog):
    op = deterministic_module_op(phrase, PROC, catalog)
    assert op is not None, f"{phrase!r} fell through to the LLM"
    assert op.action == "add"
    assert op.fields["basins"][0]["model_adapter"] == adapter


def test_wflow_basin_actually_resolves(catalog):
    state = {"slots": {}, "current_module": "processing",
             "intent": "build_forecasting_project"}
    op = deterministic_module_op("Liard uses wflow", PROC, catalog)
    TE.apply_extracted_fields(state, op, catalog)
    assert "auto/wflow_basin" in {p["pattern"] for p in state["patterns"]}


# --- 2. capabilities resolve from the patterns' own keywords --------------

@pytest.mark.parametrize("phrase,expected", [
    ("add SFINCS", "auto/coastal_sfincs"),
    ("add a hurrywave wave model", "auto/coastal_hurrywave"),
    ("CMEMS ocean grid", "auto/ocean_grid_cmems"),
    ("import SEVIRI sst", "auto/satellite_sst_SEVIRI"),
    ("add cyclone tracks", "auto/download_process_cyclone_tracks"),
    ("station csv", "auto/import_station_csv"),
    ("run delft3d", "auto/coastal_dflowfm_dimr"),
])
def test_capability_is_recognised_and_routed(phrase, expected, catalog):
    assert expected in detect_capabilities(phrase, catalog)
    op = deterministic_module_op(phrase, PROC, catalog)
    assert op is not None and op.action == "add"
    assert expected in op.fields["extra_patterns"]


def test_resolution_is_driven_by_declared_keywords(catalog):
    """No hand-maintained alias table: every match must come from a keyword
    the pattern itself declares."""
    for entry in _nameable(catalog):
        kw = str(entry.keywords[0])
        assert entry.path in detect_capabilities(f"add {kw}", catalog), (
            f"{entry.path} declares {kw!r} but isn't reachable by it"
        )


def test_capability_survives_the_resolve_rebuild(catalog):
    """resolve_patterns fully rebuilds patterns every turn, so a capability
    must live in slots (extra_patterns), not be appended to patterns."""
    state = {"slots": {}, "current_module": "processing",
             "intent": "build_data_import_only"}
    for msg in ("add GFS", "add SFINCS"):
        TE.apply_extracted_fields(
            state, deterministic_module_op(msg, PROC, catalog), catalog
        )
    TE.resolve_patterns(state, catalog)   # rebuild — must not lose it
    paths = {p["pattern"] for p in state["patterns"]}
    assert "auto/coastal_sfincs" in paths
    assert "auto/nwp_grid_noaa" in paths


def test_capability_detector_does_not_fire_on_plain_imports(catalog):
    for phrase in ("add GFS", "add ECMWF", "use precipitation",
                   "the Gulf of Guinea"):
        assert detect_capabilities(phrase, catalog) == []


# --- 3. anything addable must render + XSD-validate -----------------------

def test_every_nameable_capability_renders_or_reports_what_it_needs(catalog):
    """Addable == required variables all defaulted. Those must render clean;
    the rest must name what they still need rather than be added broken."""
    for entry in _nameable(catalog):
        req = capability_required_variables(entry.path, catalog)
        if req:
            continue  # reported to the user, never auto-added
        bp = Blueprint(
            name="t", output_root=Path("out"),
            patterns=[PatternRef(pattern=entry.path, instances=[{}])],
        )
        res = expand(bp, REPO / "fews_agent" / "patterns")
        assert not res.errors, f"{entry.path}: {res.errors}"
        assert res.rendered_files, f"{entry.path} rendered nothing"
        for f in res.rendered_files:
            if f.relpath.lower().endswith(".xml"):
                ok, msg = validate_xsd(f.content.encode("utf-8"))
                assert ok, f"{entry.path} -> {f.relpath}: {msg}"


# --- 4. capabilities we can't guess at fail LOUDLY ------------------------

@pytest.mark.parametrize("phrase", [
    "set up archive import", "use the cds api", "archive export",
])
def test_capability_needing_input_is_reported_not_added(phrase, catalog):
    hits = detect_capabilities(phrase, catalog)
    addable, needs = split_addable_capabilities(hits, catalog)
    assert needs, f"{phrase!r} should report what it needs"
    assert addable == [], "a pattern with required vars must not be auto-added"
    path, needed = needs[0]
    assert needed == capability_required_variables(path, catalog)
