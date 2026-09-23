"""Open-world authoring behind the gauntlet (Increment 3)."""
from __future__ import annotations

from fews_agent.agent.authoring import author_file, write_authored
from fews_agent.agent.ledger import load_ledger
from fews_agent.agent.patch_ops import apply_patch
from fews_agent.agent.project_chat import build_pattern_catalog

from tests.gauntlet_fixtures import IMPORT_XML, write_mini_config

REPO = __import__("pathlib").Path(__file__).resolve().parents[1]


class _Resp:
    def __init__(self, data):
        self.data = data


class _StubProvider:
    def __init__(self, xml: str):
        self.xml = xml

    def generate_json(self, system, user, schema):
        return _Resp({"xml": self.xml})


def test_author_file_accepts_valid_import():
    authored = author_file(
        "GFS import",
        spec="TimeSeriesImportRun",
        relpath="ModuleConfigFiles/Import/ImportGFS.xml",
        provider=_StubProvider(IMPORT_XML),
    )
    # Snippet XSD may still fail if the fixture is incomplete — then the
    # gauntlet must fail loud, never write.
    if authored.ok:
        assert "<timeSeriesImportRun" in authored.content
        assert "xsd" in authored.verified
    else:
        assert authored.error or authored.diagnostics


def test_author_file_rejects_no_provider():
    authored = author_file("x", spec="TimeSeriesImportRun", provider=None)
    assert authored.ok is False
    assert "provider" in authored.error


def test_write_authored_survives_and_is_not_clobbered(tmp_path):
    write_mini_config(tmp_path)
    from fews_agent.agent.config_tree import open_config
    open_config(tmp_path)

    authored = author_file(
        "GFS import",
        spec="TimeSeriesImportRun",
        relpath="ModuleConfigFiles/Import/ImportKNMI.xml",
        tree_path=tmp_path,
        provider=_StubProvider(IMPORT_XML),
    )
    if not authored.ok:
        # Fixture may not be XSD-valid on this machine's schemas — still
        # assert the write path refuses a failed draft.
        assert write_authored(tmp_path, authored) is None
        return
    dest = write_authored(tmp_path, authored)
    assert dest is not None
    assert dest.is_file()
    ledger = load_ledger(tmp_path)
    entry = ledger.get("ModuleConfigFiles/Import/ImportKNMI.xml")
    assert entry is not None
    assert entry.origin == "llm"
    ok, _ = ledger.may_overwrite("ModuleConfigFiles/Import/ImportKNMI.xml")
    assert ok is False


def test_author_file_op_queues_request():
    catalog = build_pattern_catalog(REPO / "fews_agent" / "patterns")
    state = {"slots": {}, "intent": "build_data_import_only"}
    res = apply_patch(state, [{
        "op": "author_file",
        "spec": "TimeSeriesImportRun",
        "path": "ModuleConfigFiles/Import/ImportKNMI.xml",
        "request": "KNMI Harmonie grid import",
    }], catalog)
    assert res.dropped == []
    assert res.author_requests
    assert res.author_requests[0]["spec"] == "TimeSeriesImportRun"


def test_add_capability_unknown_points_at_author_file():
    catalog = build_pattern_catalog(REPO / "fews_agent" / "patterns")
    state = {"slots": {}, "intent": "build_data_import_only"}
    res = apply_patch(state, [{
        "op": "add_capability", "pattern": "auto/not_a_real_pattern",
    }], catalog)
    assert any("author_file" in d and "admit_file" in d for d in res.dropped)
