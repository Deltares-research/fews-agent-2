"""Transcript rendering: call->result pairing (the bug worth pinning)."""
from __future__ import annotations

import json

from runners.react.transcript_md import render


def _log(tmp_path, events: list[dict]):
    session = tmp_path / "sess"
    session.mkdir()
    path = session / "react_log.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events),
                    encoding="utf-8")
    return path


def test_pairs_parallel_results_by_id_not_order(tmp_path):
    # Results arrive in COMPLETION order (b before a) — pairing must
    # follow tool_call_id, not sequence.
    events = [
        {"kind": "user", "text": "do it"},
        {"kind": "assistant", "iteration": 1, "text": "", "tool_calls": [
            {"id": "a", "name": "read_project_file",
             "arguments": {"path": "A.xml"}},
            {"id": "b", "name": "read_project_file",
             "arguments": {"path": "B.xml"}},
        ]},
        {"kind": "tool_result", "name": "read_project_file",
         "tool_call_id": "b",
         "content": json.dumps({"path": "B.xml", "content": "bb"})},
        {"kind": "tool_result", "name": "read_project_file",
         "tool_call_id": "a",
         "content": json.dumps({"path": "A.xml", "content": "a"})},
        {"kind": "assistant", "iteration": 2, "text": "done",
         "tool_calls": []},
        {"kind": "stop", "reason": "final"},
    ]
    md = render(_log(tmp_path, events), [])
    b_line = md.index("path=B.xml")
    a_line = md.index("path=A.xml")
    # Each call line is immediately followed by ITS result.
    assert "path=B.xml\n  → read `B.xml`" in md
    assert "path=A.xml\n  → read `A.xml`" in md
    assert b_line < a_line          # rendered in result order
    assert "**Response**" in md and "done" in md
    assert "## Turn 1 — user" in md and "do it" in md


def test_legacy_log_without_ids_pairs_on_echoed_path(tmp_path):
    # Older logs stored no call ids; two same-name calls are
    # disambiguated by the identifying value the result echoes.
    events = [
        {"kind": "assistant", "iteration": 1, "text": "", "tool_calls": [
            {"name": "read_example", "arguments": {"path": "X.xml"}},
            {"name": "read_example", "arguments": {"path": "Y.xml"}},
        ]},
        {"kind": "tool_result", "name": "read_example",
         "content": json.dumps({"path": "Y.xml", "content": "y"})},
        {"kind": "tool_result", "name": "read_example",
         "content": json.dumps({"path": "X.xml", "content": "x"})},
        {"kind": "stop", "reason": "final"},
    ]
    md = render(_log(tmp_path, events), ["my prompt"])
    assert "path=Y.xml\n  → read `Y.xml`" in md
    assert "path=X.xml\n  → read `X.xml`" in md
    assert "my prompt" in md        # prompt supplied for a log w/o user events


def test_write_and_validate_digests(tmp_path):
    events = [
        {"kind": "user", "text": "build"},
        {"kind": "assistant", "iteration": 1, "text": "", "tool_calls": [
            {"id": "w", "name": "write_config_file",
             "arguments": {"schema": "Workflow",
                           "output_path": "WorkflowFiles/W.xml",
                           "data": {"version": "1.1", "activity": []}}},
        ]},
        {"kind": "tool_result", "name": "write_config_file",
         "tool_call_id": "w",
         "content": json.dumps({"ok": True, "path": "WorkflowFiles/W.xml",
                                "overwrote": True})},
        {"kind": "assistant", "iteration": 2, "text": "", "tool_calls": [
            {"id": "v", "name": "validate_project", "arguments": {}},
        ]},
        {"kind": "tool_result", "name": "validate_project",
         "tool_call_id": "v",
         "content": json.dumps({"files": 3, "xsd_failures": [],
                                "undefined_properties": [],
                                "expression_issues": [],
                                "semantic": {"unresolved_count": 0}})},
        {"kind": "assistant", "iteration": 3, "text": "built",
         "tool_calls": []},
        {"kind": "stop", "reason": "final"},
    ]
    md = render(_log(tmp_path, events), [])
    assert "Workflow -> WorkflowFiles/W.xml" in md
    assert "wrote `WorkflowFiles/W.xml` (overwrote)" in md
    assert "3 files · 0 XSD failures · 0 unresolved refs" in md


def test_early_stop_is_flagged(tmp_path):
    events = [
        {"kind": "user", "text": "go"},
        {"kind": "assistant", "iteration": 1, "text": "", "tool_calls": [
            {"id": "a", "name": "list_specs", "arguments": {}}]},
        {"kind": "tool_result", "name": "list_specs", "tool_call_id": "a",
         "content": json.dumps({"count": 2, "specs": "x\ny"})},
        {"kind": "stop", "reason": "max_iterations"},
    ]
    md = render(_log(tmp_path, events), [])
    assert "turn ended early: max_iterations" in md
    assert "2 specs" in md
