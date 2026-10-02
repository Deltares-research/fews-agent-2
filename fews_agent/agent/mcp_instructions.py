"""Leftover FastMCP ``instructions`` (skills call ``fews-check``).

A namespace hint only. Procedure lives in the ``fews-config`` skill.
Pattern → Jinja remains in ``generation_tools`` for manual/legacy calls.
"""

MCP_INSTRUCTIONS = """\
Delft-FEWS configuration agent. Path is the key (no session_id).

Nothing reaches disk unverified: draft → validate → admit_file.

TYPED PATH (prefer): schema_shape → fill JSON → render_spec → admit_file.
Raw XML only when no spec fits: schema_shape + find_examples → validate_xml → admit_file.
Patterns are a last farmed snapshot that passed XSD, not operationally correct XML — examples via find_examples, not a generator.

Do not call list_patterns, create_project, apply_slots, or build_project
as part of routing. If build_project is invoked anyway, it must not
clobber origin=human or origin=llm files.

VALIDATE A FOLDER: open_config_folder (once; ledger only) → validate_config.
id_registry before reusing IDs. Do not invent parameterId / moduleInstanceId
/ idMapId.

SNIPPET vs FOLDER: pasted XML → validate_xml. A directory → validate_config.

REPAIR: explain_diagnostic(rule_id) → repair from fix_hint → re-validate.
Do not admit_file until ok.

Coding agents: fews-check --json. Procedure: fews-config skill.
"""
