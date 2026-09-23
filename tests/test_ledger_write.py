"""write_output honours the provenance ledger."""
from __future__ import annotations

from fews_agent.agent.authoring import AuthoredFile, write_authored
from fews_agent.agent.blueprint import ExpandResult, RenderedFile, write_output
from fews_agent.agent.ledger import Ledger, fingerprint, load_ledger


def _rf(relpath: str, content: str, pattern: str = "auto/nwp_grid_noaa") -> RenderedFile:
    return RenderedFile(
        relpath=relpath, content=content, pattern=pattern, instance_label="GFS",
    )


def test_write_output_marks_real_relpaths(tmp_path):
    rel = "ModuleConfigFiles/Import/ImportGFS.xml"
    result = ExpandResult(rendered_files=[_rf(rel, "<a/>")])
    manifest = write_output(result, tmp_path)
    assert manifest["written"][0]["path"] == rel
    assert manifest["skipped"] == []
    ledger = load_ledger(tmp_path)
    entry = ledger.get(rel)
    assert entry is not None
    assert entry.origin == "pattern"
    assert entry.pattern == "auto/nwp_grid_noaa"
    assert (tmp_path / rel).read_text(encoding="utf-8") == "<a/>"


def test_write_output_skips_llm_file(tmp_path):
    rel = "ModuleConfigFiles/Custom/ImportKNMI.xml"
    authored = AuthoredFile(
        relpath=rel, content="<knmi/>", ok=True, verified=["xsd", "conform"],
    )
    write_authored(tmp_path, authored)
    before = (tmp_path / rel).read_bytes()
    result = ExpandResult(rendered_files=[_rf(rel, "<clobber/>")])
    manifest = write_output(result, tmp_path)
    assert any(s["path"] == rel for s in manifest["skipped"])
    assert (tmp_path / rel).read_bytes() == before
    assert load_ledger(tmp_path).get(rel).origin == "llm"


def test_write_output_skips_drifted_pattern(tmp_path):
    rel = "ModuleConfigFiles/Import/ImportGFS.xml"
    write_output(ExpandResult(rendered_files=[_rf(rel, "<orig/>")]), tmp_path)
    dest = tmp_path / rel
    dest.write_text("<human-edit/>", encoding="utf-8")
    ledger = load_ledger(tmp_path)
    assert ledger.drifted_pattern(rel, dest.read_bytes())
    manifest = write_output(
        ExpandResult(rendered_files=[_rf(rel, "<rebuild/>")]), tmp_path,
    )
    assert any("drifted" in s["reason"] for s in manifest["skipped"])
    assert dest.read_text(encoding="utf-8") == "<human-edit/>"


def test_clean_pattern_rebuild_refreshes_fingerprint(tmp_path):
    rel = "ModuleConfigFiles/Import/ImportGFS.xml"
    write_output(ExpandResult(rendered_files=[_rf(rel, "<v1/>")]), tmp_path)
    manifest = write_output(
        ExpandResult(rendered_files=[_rf(rel, "<v2/>")]), tmp_path,
    )
    assert manifest["skipped"] == []
    assert (tmp_path / rel).read_text(encoding="utf-8") == "<v2/>"
    entry = load_ledger(tmp_path).get(rel)
    assert entry.fingerprint == fingerprint(b"<v2/>")


def test_may_overwrite_matrix(tmp_path):
    ledger = Ledger(root=tmp_path)
    assert ledger.may_overwrite("new.xml")[0] is True
    ledger.mark_llm("llm.xml", b"<x/>", ["xsd"])
    assert ledger.may_overwrite("llm.xml")[0] is False
    ledger.files["human.xml"] = ledger.files["llm.xml"].__class__(
        origin="human", fingerprint=fingerprint(b"<h/>"),
    )
    assert ledger.may_overwrite("human.xml")[0] is False
    ledger.mark_pattern("p.xml", "auto/x", data=b"<p/>")
    assert ledger.may_overwrite("p.xml", b"<p/>")[0] is True
    ok, reason = ledger.may_overwrite("p.xml", b"<edited/>")
    assert ok is False
    assert "drifted" in reason
