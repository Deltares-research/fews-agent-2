"""Path-based generation tools (MCP Layer 3)."""
from __future__ import annotations

from fews_agent.agent.generation_tools import (
    tool_admit_file,
    tool_apply_slots,
    tool_build_project,
    tool_create_project,
    tool_list_patterns,
)
from fews_agent.agent.ledger import load_ledger
from fews_agent.validation.gauntlet import validate_xml

from tests.gauntlet_fixtures import IMPORT_XML


def test_list_patterns_gfs():
    out = tool_list_patterns("GFS")
    paths = [p["path"] for p in out["patterns"]]
    assert any("nwp_grid_noaa" in p for p in paths)


def test_create_apply_mystery_is_dropped(tmp_path):
    created = tool_create_project(str(tmp_path), name="mystery")
    assert created["reopened"] is False
    out = tool_apply_slots(
        str(tmp_path),
        [{"op": "add_import", "name": "MysteryModel"}],
    )
    assert out["dropped"]
    assert not out.get("patterns")


def test_create_apply_build_gfs(tmp_path):
    tool_create_project(str(tmp_path), name="gfs-only")
    applied = tool_apply_slots(
        str(tmp_path),
        [{"op": "add_import", "name": "GFS"}],
    )
    assert not applied.get("dropped")
    assert any(
        "nwp_grid_noaa" in (p.get("pattern") or "")
        for p in applied["patterns"]
    )
    built = tool_build_project(str(tmp_path), phase="imports")
    assert "error" not in built, built
    assert built["files_total"] >= 1
    assert built["files_xsd_ok"] == built["files_xml"]
    generated = tmp_path / "generated"
    xmls = list(generated.rglob("*.xml"))
    assert xmls
    ledger = load_ledger(generated)
    assert any(e.origin == "pattern" for e in ledger.files.values())


def test_admit_file_then_rebuild_leaves_llm(tmp_path):
    tool_create_project(str(tmp_path), name="admit-demo")
    tool_apply_slots(str(tmp_path), [{"op": "add_import", "name": "GFS"}])
    rel = "ModuleConfigFiles/Custom/ImportKNMI.xml"
    report = validate_xml(IMPORT_XML, spec="TimeSeriesImportRun", tiers=["xsd", "conform"])
    xml = IMPORT_XML
    if not report.ok:
        # Snippet may fail XSD; admit_file must refuse rather than write.
        admitted = tool_admit_file(str(tmp_path), rel, xml, spec="TimeSeriesImportRun")
        assert admitted["ok"] is False
        return
    admitted = tool_admit_file(str(tmp_path), rel, xml, spec="TimeSeriesImportRun")
    assert admitted["ok"] is True
    dest = tmp_path / "generated" / rel
    before = dest.read_bytes()
    tool_build_project(str(tmp_path))
    assert dest.is_file()
    assert dest.read_bytes() == before
    assert load_ledger(tmp_path / "generated").get(rel).origin == "llm"
