"""fews-check CLI: JSON in/out, exit codes, admit is the write gate."""
from __future__ import annotations

import json
from pathlib import Path

from fews_agent.cli.check import main

WORKFLOW_DATA = {
    "version": "1.1",
    "activity": [
        {"moduleInstanceId": "ImportGFS", "runIndependent": True},
    ],
}


def _run(argv: list[str], capsys) -> tuple[int, dict]:
    code = main(argv)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    return code, payload


def test_schema_shape_workflow(capsys):
    code, payload = _run(["--json", "schema-shape", "Workflow"], capsys)
    assert code == 0
    assert payload.get("error") is None
    assert payload["name"] == "Workflow"
    assert "required" in payload


def test_schema_shape_unknown_exits_1(capsys):
    code, payload = _run(["schema-shape", "NotARealSpec"], capsys)
    assert code == 1
    assert "error" in payload
    assert payload.get("known_specs_sample")


def test_render_spec_from_file(tmp_path, capsys):
    data = tmp_path / "payload.json"
    data.write_text(json.dumps(WORKFLOW_DATA), encoding="utf-8")
    code, payload = _run(
        ["--json", "render-spec", "Workflow", "--data", str(data)],
        capsys,
    )
    assert code == 0
    assert payload["ok"] is True
    assert "<workflow" in payload["xml"]
    assert "ImportGFS" in payload["xml"]
    assert payload["suggested_relpath"].startswith("WorkflowFiles/")


def test_render_spec_bad_json_exits_1(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    code, payload = _run(
        ["render-spec", "Workflow", "--data", str(bad)],
        capsys,
    )
    assert code == 1
    assert payload["ok"] is False
    assert payload["validation_errors"]


def test_json_flag_stripped_anywhere(tmp_path, capsys):
    data = tmp_path / "payload.json"
    data.write_text(json.dumps(WORKFLOW_DATA), encoding="utf-8")
    code, payload = _run(
        ["render-spec", "Workflow", "--data", str(data), "--json"],
        capsys,
    )
    assert code == 0
    assert payload["ok"] is True


def test_admit_from_render_writes(tmp_path, capsys):
    data = tmp_path / "payload.json"
    data.write_text(json.dumps(WORKFLOW_DATA), encoding="utf-8")
    code, rendered = _run(
        ["render-spec", "Workflow", "--data", str(data)],
        capsys,
    )
    assert code == 0 and rendered["ok"]
    render_path = tmp_path / "render.json"
    render_path.write_text(json.dumps(rendered), encoding="utf-8")
    dest = tmp_path / "config"
    dest.mkdir()
    code, admitted = _run(
        ["admit", str(dest), "--from-render", str(render_path)],
        capsys,
    )
    assert code == 0
    assert admitted["ok"] is True
    written = Path(admitted["written"])
    assert written.is_file()
    assert "ImportGFS" in written.read_text(encoding="utf-8")
    assert admitted["origin"] == "llm"


def test_admit_rejects_failed_render(tmp_path, capsys):
    render_path = tmp_path / "render.json"
    render_path.write_text(
        json.dumps({"ok": False, "xml": "<workflow/>", "suggested_relpath": "x.xml"}),
        encoding="utf-8",
    )
    dest = tmp_path / "config"
    dest.mkdir()
    code, payload = _run(
        ["admit", str(dest), "--from-render", str(render_path)],
        capsys,
    )
    assert code == 1
    assert payload["ok"] is False
    assert not list(dest.rglob("*.xml"))


def test_admit_requires_xml_or_from_render(tmp_path, capsys):
    dest = tmp_path / "config"
    dest.mkdir()
    code, payload = _run(["admit", str(dest), "--relpath", "x.xml"], capsys)
    assert code == 1
    assert "error" in payload


def test_validate_xml_workflow(tmp_path, capsys):
    data = tmp_path / "payload.json"
    data.write_text(json.dumps(WORKFLOW_DATA), encoding="utf-8")
    _, rendered = _run(
        ["render-spec", "Workflow", "--data", str(data)],
        capsys,
    )
    xml_path = tmp_path / "wf.xml"
    xml_path.write_text(rendered["xml"], encoding="utf-8")
    code, report = _run(
        ["validate-xml", "--xml", str(xml_path), "--spec", "Workflow"],
        capsys,
    )
    assert code == 0
    assert report["ok"] is True


def test_explain(capsys):
    code, payload = _run(["explain", "xsd.schema"], capsys)
    assert code == 0
    assert payload["rule_id"] == "xsd.schema"
    assert "fix_hint" in payload


def test_explain_unknown(capsys):
    code, payload = _run(["explain", "not.a.rule"], capsys)
    assert code == 1
    assert "error" in payload


def test_find_examples(capsys):
    code, payload = _run(["find-examples", "GFS", "-k", "2"], capsys)
    assert code == 0
    assert payload["query"] == "GFS"
    assert "examples" in payload


def test_validate_config_on_empty_tree(tmp_path, capsys):
    dest = tmp_path / "empty"
    dest.mkdir()
    code, payload = _run(["validate-config", str(dest)], capsys)
    assert code in (0, 1)
    assert "ok" in payload or "diagnostics" in payload


def test_open_config_and_id_registry(tmp_path, capsys):
    dest = tmp_path / "empty"
    dest.mkdir()
    code, opened = _run(["open-config", str(dest)], capsys)
    assert code == 0
    assert opened is not None
    assert (dest / ".fews-agent" / "ledger.yaml").is_file()
    code, ids = _run(["id-registry", str(dest)], capsys)
    assert code == 0
    assert "declared" in ids


def test_missing_data_file(capsys):
    code, payload = _run(
        ["render-spec", "Workflow", "--data", "C:/definitely/not/here.json"],
        capsys,
    )
    assert code == 1
    assert payload["ok"] is False
    assert "error" in payload


def test_usage_error_exits_nonzero(capsys):
    code = main([])
    assert code != 0
    err = capsys.readouterr()
    assert err.err
