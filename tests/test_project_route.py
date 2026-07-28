"""The project route (GPS) — deterministic position on the path to a complete
config. These pin the navigation the tester histories showed was missing:
after adding a source the next step is its VARIABLES, not a build push; the
project is not 'ready to assemble' until the blocking legs are done.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fews_agent.agent import turn_engine as TE
from fews_agent.agent.project_chat import build_pattern_catalog
from fews_agent.agent.project_route import route_digest, route_position

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalog():
    return build_pattern_catalog(REPO / "fews_agent" / "patterns")


def _state(catalog, slots, intent="build_data_import_only", **extra):
    st = {"slots": dict(slots), "intent": intent, **extra}
    TE.resolve_patterns(st, catalog)
    return st


def _leg(pos, leg_id):
    return next(lg for lg in pos.legs if lg.id == leg_id)


# --- empty project ----------------------------------------------------------

def test_empty_project_current_is_add_a_source(catalog, tmp_path):
    pos = route_position(_state(catalog, {}), tmp_path)
    assert pos.current.id == "capability"
    assert not pos.ready_to_assemble
    assert not pos.assembled


# --- the core navigation the histories were missing -------------------------

def test_after_adding_source_next_step_is_variables_not_build(catalog, tmp_path):
    """The 'too eager to build / forgot the variables' fix: a freshly added
    GFS on defaults makes the source_variables leg the current step."""
    pos = route_position(_state(catalog, {"imports": ["GFS"]}), tmp_path)
    assert pos.current.id == "source_variables"
    assert "default" in pos.current.guidance.lower()
    # ...and assembly is NOT offered yet (required CSVs still missing).
    assert not pos.ready_to_assemble
    digest = route_digest(_state(catalog, {"imports": ["GFS"]}), tmp_path)
    assert "NEXT STEP" in digest and "variable" in digest.lower()
    assert "NOT yet" in digest


def test_choosing_variables_completes_that_leg(catalog, tmp_path):
    pos = route_position(
        _state(catalog, {"imports": ["GFS"], "data_types": ["precipitation"]}),
        tmp_path)
    assert _leg(pos, "source_variables").done
    assert pos.current.id != "source_variables"


def test_per_import_parameters_override_also_completes_variables(catalog, tmp_path):
    """Removing a variable writes a per-import parameters override — that
    counts as 'chosen', so the leg is done (no stale 'set variables' nag)."""
    st = _state(catalog, {"imports": ["GFS"],
                          "import_overrides": {"GFS": {"parameters": [
                              {"id": "PC.nwp"}]}}})
    assert _leg(route_position(st, tmp_path), "source_variables").done


def test_eccc_import_has_no_variables_leg(catalog, tmp_path):
    """HRDPS carries a FIXED parameter set — the variables leg doesn't apply,
    so it never becomes the 'you forgot variables' step."""
    pos = route_position(_state(catalog, {"imports": ["HRDPS"]}), tmp_path)
    assert not _leg(pos, "source_variables").active


def test_digest_names_fixed_variable_sources_derived(catalog, tmp_path):
    """The 'don't ask which variables' fact is DERIVED from the catalog and
    stated in the digest — not a hardcoded prompt list (no drift). NOAA is
    selectable, so it's never listed as fixed."""
    d_eccc = route_digest(_state(catalog, {"imports": ["HRDPS"]}), tmp_path)
    assert "Fixed variable set" in d_eccc and "HRDPS" in d_eccc
    d_noaa = route_digest(_state(catalog, {"imports": ["GFS"]}), tmp_path)
    assert "Fixed variable set" not in d_noaa


# --- basin adapter leg ------------------------------------------------------

def test_basin_without_adapter_is_the_blocking_step(catalog, tmp_path):
    st = _state(catalog, {"basins": [{"basin_name": "Rhine"}]},
                intent="build_basin_model_only")
    pos = route_position(st, tmp_path)
    assert pos.current.id == "basin_adapter"
    assert "Rhine" in pos.current.guidance
    assert not pos.ready_to_assemble


def test_basin_with_adapter_clears_it(catalog, tmp_path):
    st = _state(catalog,
                {"basins": [{"basin_name": "Rhine", "model_adapter": "wflow"}]},
                intent="build_basin_model_only")
    assert _leg(route_position(st, tmp_path), "basin_adapter").done


# --- map area is advisory, never blocking -----------------------------------

def test_map_area_is_advisory_not_blocking(catalog, tmp_path):
    pos = route_position(
        _state(catalog, {"imports": ["GFS"], "data_types": ["precipitation"]}),
        tmp_path)
    ma = _leg(pos, "map_area")
    assert ma.kind == "advisory" and ma.active and not ma.done
    assert ma in pos.advisory_open
    assert ma not in pos.blocking_open
    # region set → leg done
    st2 = _state(catalog, {"imports": ["GFS"], "data_types": ["precipitation"],
                           "region": "North Sea"})
    assert _leg(route_position(st2, tmp_path), "map_area").done


# --- required inputs block assembly -----------------------------------------

def test_required_inputs_block_until_present(catalog, tmp_path):
    st = _state(catalog, {"imports": ["GFS"], "data_types": ["precipitation"]})
    pos = route_position(st, tmp_path)          # empty inputs dir
    req = _leg(pos, "required_inputs")
    assert req.kind == "blocking" and not req.done
    assert not pos.ready_to_assemble

    (tmp_path / "locations.csv").write_text("id,lat,lon\nA,1,2\n",
                                             encoding="utf-8")
    (tmp_path / "parameters.csv").write_text("id\nPC.nwp\n", encoding="utf-8")
    st_ready = _state(catalog, {"imports": ["GFS"],
                                "data_types": ["precipitation"],
                                "region": "North Sea"})   # map_area also done
    pos2 = route_position(st_ready, tmp_path)
    assert _leg(pos2, "required_inputs").done
    assert pos2.ready_to_assemble            # nothing blocking left
    assert pos2.current.id == "assemble"     # the terminal step is now current

    # With an advisory still open (no region), 'current' is that advisory even
    # though the project is already assemblable — the driver may skip it.
    pos_adv = route_position(st, tmp_path)
    assert pos_adv.ready_to_assemble
    assert pos_adv.current.id == "map_area"


def test_assembled_project_reports_done(catalog, tmp_path):
    (tmp_path / "locations.csv").write_text("id,lat,lon\nA,1,2\n",
                                             encoding="utf-8")
    (tmp_path / "parameters.csv").write_text("id\nPC.nwp\n", encoding="utf-8")
    st = _state(catalog, {"imports": ["GFS"], "data_types": ["precipitation"]},
                full_build_ok=True)
    pos = route_position(st, tmp_path)
    assert pos.assembled
    assert pos.current is None               # journey complete
    assert "assembled successfully" in route_digest(st, tmp_path)


# --- digest shape -----------------------------------------------------------

def test_digest_leads_with_next_step_and_gates_assembly(catalog, tmp_path):
    d = route_digest(_state(catalog, {"imports": ["GFS"]}), tmp_path)
    lines = d.splitlines()
    assert any(l.startswith("NEXT STEP") for l in lines)
    assert any("Ready to assemble" in l for l in lines)
