"""End-to-end: a module-mode chat session drives a real, XSD-valid build.

Every other module-mode test stubs a piece. This one drives the full CLI
loop — cold entry from prose, the extractor applying an operation, `done`
writing project.yaml — and then runs the deterministic build on that
project.yaml, asserting the output is XSD-valid. The `projects/` fixtures
are gitignored, so this test IS the durable oracle for "module-mode
produces a working config".

Only the extractor's LLM is stubbed (the build path needs no LLM — the
filter drafter falls back to the bundled standard). It exercises the weld:
one prose capability must emit its ModuleConfig + Workflow + IdMap files
together.
"""
from __future__ import annotations

import glob
import io
from pathlib import Path

import pytest
from rich.console import Console

from runners.agent import chat_step
from runners.agent.build_from_blueprint import build_from_blueprint

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PATTERNS_ROOT = _REPO_ROOT / "fews_agent" / "patterns"


class _Resp:
    def __init__(self, data):
        self.data = data


class _Provider:
    """Extractor stub: every prose turn resolves to a confident GFS+HRDPS add."""

    def generate_json(self, system, user, schema):
        return _Resp({
            "action": "add",
            "confidence": 0.9,
            "fields": {
                "imports": ["GFS", "HRDPS"],
                "data_types": ["precipitation", "temperature"],
            },
        })


@pytest.fixture
def driven(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_step, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(chat_step, "_resolve_provider", lambda model: _Provider())
    return tmp_path


def _build(project_dir_root: Path, name: str) -> dict:
    bp = Path(glob.glob(str(project_dir_root / name / "*" / "project.yaml"))[0])
    return build_from_blueprint(
        blueprint_path=bp, pattern_root=_PATTERNS_ROOT,
        console=Console(file=io.StringIO(), force_terminal=False),
    )


def test_cold_entry_prose_to_valid_build(driven):
    # Cold entry ("imports module") + one-shot add, then done → project.yaml.
    rc1 = chat_step.main([
        "--project-name", "e2e",
        "--message", "set up the imports module with GFS and HRDPS, "
                     "precip and temperature",
    ])
    assert rc1 == 0
    rc2 = chat_step.main(["--project-name", "e2e", "--message", "done"])
    assert rc2 == 0

    summary = _build(driven, "e2e")

    # The whole rendered config is XSD-valid.
    assert summary["ok"], summary.get("errors")
    assert summary["files_xsd_ok"] == summary["files_xml"]

    # The weld: one import capability emitted its ModuleConfig + Workflow
    # (+ idMap) files together, across folders.
    paths = {f["path"].replace("\\", "/") for f in summary["files"]}
    assert any(p.endswith("ImportGFS.xml") and "ModuleConfigFiles" in p
               for p in paths)
    assert any(p.endswith("ImportGFSGrids.xml") and "WorkflowFiles" in p
               for p in paths)
    assert any(p.endswith("ImportHRDPS.xml") for p in paths)
    # every Import file that IS XML validated
    for f in summary["files"]:
        if f["path"].lower().endswith(".xml"):
            assert f["xsd_ok"], f["path"]
