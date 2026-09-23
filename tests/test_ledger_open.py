"""Brownfield ledger + open_config (Increment 2) and pattern sync (4)."""
from __future__ import annotations

from fews_agent.agent.config_tree import open_config
from fews_agent.agent.ledger import LEDGER_DIR, load_ledger, sync_patterns_from_blueprint
from fews_agent.agent.project_chat import initial_state, write_project

from tests.gauntlet_fixtures import write_mini_config


def test_open_config_marks_human_and_does_not_rewrite_xml(tmp_path):
    write_mini_config(tmp_path)
    target = tmp_path / "ModuleConfigFiles" / "Import" / "ImportGLOBSNOW.xml"
    before = target.read_bytes()
    summary = open_config(tmp_path)
    assert summary["files"] >= 1
    assert summary["ledger_origins"].get("human", 0) >= 1
    assert target.read_bytes() == before
    ledger = load_ledger(tmp_path)
    rel = "ModuleConfigFiles/Import/ImportGLOBSNOW.xml"
    entry = ledger.get(rel)
    assert entry is not None
    assert entry.origin == "human"
    ok, reason = ledger.may_overwrite(rel)
    assert ok is False
    assert "human" in reason


def test_open_config_round_trip_byte_identical(tmp_path):
    write_mini_config(tmp_path)
    xmls = {
        p.relative_to(tmp_path): p.read_bytes()
        for p in tmp_path.rglob("*.xml")
    }
    open_config(tmp_path)
    open_config(tmp_path)  # second open must not mutate XML
    for rel, data in xmls.items():
        assert (tmp_path / rel).read_bytes() == data


def test_write_project_syncs_pattern_ledger(tmp_path):
    state = initial_state("ledger-demo")
    state["patterns"] = [
        {"pattern": "auto/nwp_grid_noaa", "instances": [{"nwp_name": "GFS"}]},
    ]
    write_project(state, tmp_path)
    ledger = load_ledger(tmp_path)
    keys = [k for k in ledger.files if k.startswith("pattern:auto/nwp_grid_noaa")]
    assert keys
    assert ledger.get(keys[0]).origin == "pattern"
    assert (tmp_path / LEDGER_DIR / "ledger.yaml").is_file()


def test_sync_does_not_clobber_human(tmp_path):
    write_mini_config(tmp_path)
    open_config(tmp_path)
    ledger = load_ledger(tmp_path)
    # Pretend a human file was also recorded under a pattern key
    human_key = next(iter(ledger.files))
    sync_patterns_from_blueprint(ledger, [
        {"pattern": "auto/nwp_grid_noaa", "instances": [{"nwp_name": "GFS"}]},
    ])
    assert ledger.get(human_key).origin == "human"
