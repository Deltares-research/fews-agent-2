"""Host-agent routing injected by FastMCP ``instructions``.

Pattern → Jinja remains in ``generation_tools`` for manual/legacy calls.
This string must not steer the host toward that path.
"""

MCP_INSTRUCTIONS = """\
Delft-FEWS configuration agent. Path is the key (no session_id).

Patterns are a last farmed snapshot that passed XSD, not operationally \
correct XML. Do not use them as the write path.

WRITE PATH (only): when a tree exists, id_registry first. Then \
schema_shape + find_examples → draft XML → validate_xml → admit_file. \
Copy parameterId / moduleInstanceId / idMapId from id_registry; do not \
invent IDs. Do not invent a pattern. admit_file is allowed even when a \
catalog name exists (GFS, Raven, …).

Do not call list_patterns, create_project, apply_slots, or \
build_project as part of routing. If build_project is invoked anyway, \
it must not clobber origin=human or origin=llm files.

VALIDATE A FOLDER: open_config_folder (once; ledger only, no XML \
rewrite) → validate_config. Add id_registry if unresolved IDs matter. \
Do not call list_patterns.

NAMING ONLY: conform_lint (folder) or conform_lint_xml (snippet). \
Prefer validate_config unless the user asked only for house naming.

SNIPPET vs FOLDER: pasted XML with no tree → validate_xml (XSD + \
conform; no cross-file IDs). A directory on disk → validate_config \
(XSD + semantic + conform + optional FEWS check).

REPAIR: on a failed gauntlet, explain_diagnostic(rule_id) → repair \
from fix_hint → re-validate the same surface (validate_xml or \
validate_config). Do not admit_file until ok.
"""
