"""Blueprint-first MCP tools — the deterministic editing surface.

Every test here is LLM-free. It drives the MCP server's helper layer
(``_apply_ops``, reverse-sync, validate, drift) the same way the typed
tools do, and asserts the contract: valid edits apply and land in
project.yaml, invalid edits drop loudly, a hand-edited blueprint round-trips
back into slots, and the generated tree's drift is detectable.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from app import mcp_server as srv
from fews_agent.agent.project_chat import (
    build_pattern_catalog,
    initial_state,
    load_blueprint_into_state,
)

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalog():
    return build_pattern_catalog(REPO / "patterns")


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    """A fresh, saved session on disk (no LLM, no build)."""
    pdir = tmp_path / "proj" / "proj_2026-01-01_000000"
    pdir.mkdir(parents=True)
    state = initial_state("proj")
    srv._save(pdir, state, [])
    return pdir


# --- _apply_ops: the shared typed-edit path -------------------------------

def test_apply_ops_add_import_writes_blueprint(project_dir):
    out = srv._apply_ops(project_dir, [{"op": "add_import", "name": "GFS"}])
    assert out["ok"] is True
    assert out["dropped"] == []
    assert "GFS" in out["imports"]
    project_yaml = project_dir / "project.yaml"
    assert project_yaml.is_file()
    data = yaml.safe_load(project_yaml.read_text(encoding="utf-8"))
    paths = {p["pattern"] for p in data["patterns"]}
    assert "auto/nwp_grid_noaa" in paths


def test_apply_ops_unknown_import_dropped_loudly(project_dir):
    out = srv._apply_ops(
        project_dir, [{"op": "add_import", "name": "MysteryModel"}]
    )
    assert out["imports"] == []
    assert any("MysteryModel" in d for d in out["dropped"])


def test_apply_ops_add_basin_unknown_adapter_dropped(project_dir):
    # The Rhine rule: never guess an adapter.
    out = srv._apply_ops(
        project_dir,
        [{"op": "add_basin", "basin_name": "Rhine", "model_adapter": "sobek"}],
    )
    assert out["basins"] == []
    assert any("sobek" in d for d in out["dropped"])


def test_apply_ops_add_basin_valid(project_dir):
    out = srv._apply_ops(
        project_dir,
        [{"op": "add_basin", "basin_name": "Liard", "model_adapter": "raven"}],
    )
    assert out["dropped"] == []
    assert "Liard" in out["basins"]
    assert "auto/raven_basin" in out["patterns"]


def test_apply_ops_scoped_scalar_override(project_dir):
    srv._apply_ops(project_dir, [{"op": "add_import", "name": "GFS"}])
    out = srv._apply_ops(
        project_dir,
        [{"op": "set_variables", "target": "GFS",
          "values": {"grid_resolution": "0p50"}}],
    )
    assert out["dropped"] == []
    data = yaml.safe_load((project_dir / "project.yaml").read_text("utf-8"))
    inst = next(
        p for p in data["patterns"] if p["pattern"] == "auto/nwp_grid_noaa"
    )["instances"][0]
    assert inst.get("grid_resolution") == "0p50"


# --- reverse-sync round-trip ----------------------------------------------

def test_blueprint_round_trip_reconstructs_slots(project_dir, catalog):
    srv._apply_ops(project_dir, [{"op": "add_import", "name": "GFS"}])
    srv._apply_ops(
        project_dir,
        [{"op": "add_basin", "basin_name": "Liard", "model_adapter": "raven"}],
    )
    # Fresh state, load only from the on-disk blueprint.
    fresh = initial_state("proj")
    notes = load_blueprint_into_state(fresh, project_dir)
    assert notes
    assert fresh["slots"]["imports"] == ["GFS"]
    assert fresh["slots"]["basins"] == [
        {"basin_name": "Liard", "model_adapter": "raven"}
    ]


def test_maybe_sync_detects_hand_edit(project_dir):
    # Hand-author a blueprint newer than the saved state.
    blueprint = {
        "name": "proj",
        "output_root": "generated",
        "patterns": [
            {"pattern": "auto/nwp_grid_noaa", "instances": [{"nwp_name": "GFS"}]}
        ],
        "singleton_seeds": {"Locations": {"geoDatum": "WGS 1984"}},
    }
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(blueprint), encoding="utf-8"
    )
    # Make project.yaml decisively newer than .chat_state.json.
    import os
    import time

    state_mtime = srv._state_path(project_dir).stat().st_mtime
    os.utime(project_dir / "project.yaml", (state_mtime + 5, state_mtime + 5))

    state, _ = srv._load(project_dir)
    notes = srv._maybe_sync_blueprint(project_dir, state)
    assert notes
    assert state["slots"]["imports"] == ["GFS"]


def test_maybe_sync_noop_when_state_is_current(project_dir):
    srv._apply_ops(project_dir, [{"op": "add_import", "name": "GFS"}])
    state, _ = srv._load(project_dir)
    # write_project + _save just ran together; no hand edit → no sync.
    assert srv._maybe_sync_blueprint(project_dir, state) == []


# --- manifest + drift ------------------------------------------------------

def _seed_generated(project_dir: Path) -> Path:
    gen = srv._generated_dir(project_dir)
    (gen / "RegionConfigFiles").mkdir(parents=True)
    f = gen / "RegionConfigFiles" / "Parameters.xml"
    f.write_text("<parameters/>\n", encoding="utf-8")
    return f


def test_manifest_then_no_drift(project_dir):
    _seed_generated(project_dir)
    srv._write_generated_manifest(project_dir)
    drift = srv._detect_drift(project_dir)
    assert drift["has_manifest"] is True
    assert drift["drifted"] is False


def test_drift_flips_on_hand_edit(project_dir):
    f = _seed_generated(project_dir)
    srv._write_generated_manifest(project_dir)
    f.write_text("<parameters><parameter id='hand'/></parameters>\n", "utf-8")
    drift = srv._detect_drift(project_dir)
    assert drift["drifted"] is True
    assert any("Parameters.xml" in c for c in drift["changed"])


def test_drift_no_manifest(project_dir):
    _seed_generated(project_dir)
    drift = srv._detect_drift(project_dir)
    assert drift["has_manifest"] is False


# --- validate --------------------------------------------------------------

def test_validate_missing_tree_errors(project_dir):
    report = srv._validate_generated(srv._generated_dir(project_dir))
    assert "error" in report


def test_validate_counts_xml(project_dir):
    _seed_generated(project_dir)
    report = srv._validate_generated(srv._generated_dir(project_dir))
    # No xsi:schemaLocation hint → validate_xsd skips (ok), so the tree passes.
    assert report["xml_total"] == 1
    assert report["xsd_ok"] == 1
    assert report["xsd_failures"] == []
