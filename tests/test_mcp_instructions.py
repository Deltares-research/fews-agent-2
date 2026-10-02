"""Pin FastMCP host routing: typed intermediate representation first, patterns not a generator."""
from __future__ import annotations

from fews_agent.agent.mcp_instructions import MCP_INSTRUCTIONS


def test_instructions_are_a_namespace_hint():
    assert len(MCP_INSTRUCTIONS) < 1024


def test_write_path_is_typed_then_admit_file():
    text = MCP_INSTRUCTIONS
    assert "admit_file" in text
    assert "schema_shape" in text
    assert "render_spec" in text
    assert "find_examples" in text
    assert "validate_xml" in text
    assert "TYPED PATH" in text


def test_farmed_snapshot_is_not_correct_xml():
    text = MCP_INSTRUCTIONS.lower()
    assert "farmed snapshot" in text
    assert "not operationally" in text
    assert "not a generator" in text or "not a generator" in MCP_INSTRUCTIONS


def test_validate_folder_does_not_require_list_patterns():
    text = MCP_INSTRUCTIONS
    assert "VALIDATE A FOLDER" in text
    assert "open_config_folder" in text
    assert "validate_config" in text
    folder = text[text.index("VALIDATE A FOLDER"):]
    assert "Do not invent" in folder or "id_registry" in folder


def test_repair_loop_uses_explain_diagnostic():
    text = MCP_INSTRUCTIONS
    assert "explain_diagnostic" in text
    assert "REPAIR" in text
    assert "fix_hint" in text


def test_snippet_vs_folder():
    text = MCP_INSTRUCTIONS
    assert "SNIPPET vs FOLDER" in text
    assert "validate_xml" in text
    assert "validate_config" in text


def test_points_at_skill():
    assert "fews-config" in MCP_INSTRUCTIONS
    assert "fews-check" in MCP_INSTRUCTIONS


def test_no_always_list_patterns_first():
    assert "ALWAYS call list_patterns first" not in MCP_INSTRUCTIONS


def test_no_catalog_handwrite_ban():
    assert "Do NOT hand-write XML for a catalog pattern" not in MCP_INSTRUCTIONS
    assert "Do not hand-write XML for a catalog pattern" not in MCP_INSTRUCTIONS


def test_no_recommended_generator_sequence():
    text = MCP_INSTRUCTIONS
    assert "create_project → apply_slots → build_project" not in text
    assert "create_project -> apply_slots -> build_project" not in text


def test_no_opt_in_generator_routing():
    lower = MCP_INSTRUCTIONS.lower()
    assert "opt-in" not in lower
    assert "if the user asks" not in lower
