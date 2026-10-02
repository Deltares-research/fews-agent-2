"""Leftover MCP server — verification toolbelt + path-based generation.

Coding agents should call ``fews-check``, not these tools. Logic lives
in ``fews_agent.validation.toolbelt`` and
``fews_agent.agent.generation_tools``; this module only serializes JSON.

Host routing prefers a typed intermediate representation (``MCP_INSTRUCTIONS``). Generation
tools stay registered for manual/legacy calls and are not a host route.

    python -m app.mcp_server

Register with Cursor / VS Code (``.vscode/mcp.json``) or Claude Desktop
using ``python -m app.mcp_server`` and ``cwd`` = this repo.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env", override=False)
except ImportError:
    pass

from mcp.server.fastmcp import FastMCP

from fews_agent.agent.config_tree import open_config
from fews_agent.agent.generation_tools import (
    tool_admit_file,
    tool_apply_slots,
    tool_build_project,
    tool_create_project,
    tool_list_patterns,
)
from fews_agent.agent.mcp_instructions import MCP_INSTRUCTIONS
from fews_agent.validation.toolbelt import (
    tool_conform_lint,
    tool_conform_lint_xml,
    tool_explain_diagnostic,
    tool_find_examples,
    tool_id_registry,
    tool_render_spec,
    tool_schema_shape,
    tool_validate_config,
    tool_validate_xml,
)

mcp = FastMCP("fews-agent", instructions=MCP_INSTRUCTIONS)


def _dumps(payload: dict) -> str:
    return json.dumps(payload, indent=2, default=str)


@mcp.tool()
def validate_config(path: str, tiers: str | None = None) -> str:
    """Run XSD + semantic + conform + FEWS check on a config folder.

    When: a FEWS directory on disk — default for "check this config."

    Args:
        path: Absolute path to a FEWS config tree.
        tiers: Optional comma-separated subset: xsd,semantic,conform,fews_check.
    """
    parsed = [t.strip() for t in tiers.split(",")] if tiers else None
    return _dumps(tool_validate_config(path, tiers=parsed))


@mcp.tool()
def validate_xml(xml: str, spec: str | None = None) -> str:
    """Validate a pasted FEWS XML snippet against the pinned XSD (+ conform).

    When: pasted XML, no disk tree. No cross-file ID check.
    """
    return _dumps(tool_validate_xml(xml, spec=spec))


@mcp.tool()
def conform_lint(path: str) -> str:
    """FEWS-Conform naming lint on a config folder.

    When: naming only. Not a substitute for XSD or semantic; prefer
    validate_config unless the user asked only for house naming.
    """
    return _dumps(tool_conform_lint(path))


@mcp.tool()
def conform_lint_xml(xml: str, spec: str | None = None) -> str:
    """FEWS-Conform lint on a pasted snippet (remote-safe).

    When: naming only on pasted XML. Not a substitute for XSD.
    """
    return _dumps(tool_conform_lint_xml(xml, spec=spec))


@mcp.tool()
def schema_shape(spec: str) -> str:
    """Pinned Pydantic/XSD shape for a spec (e.g. TimeSeriesImportRun).

    When: before drafting XML. Grammar, not a generator.
    """
    return _dumps(tool_schema_shape(spec))


@mcp.tool()
def render_spec(spec: str, data: str) -> str:
    """Fill a Pydantic spec with JSON, render XML via the registered template.

    When: preferred write path after schema_shape. Pass data as a JSON
    object string. Read-only — write the returned xml with admit_file.
    """
    try:
        payload = json.loads(data) if isinstance(data, str) else data
    except json.JSONDecodeError as exc:
        return _dumps({
            "spec": spec,
            "ok": False,
            "xml": "",
            "suggested_relpath": None,
            "diagnostics": [],
            "validation_errors": [{
                "loc": ["data"],
                "msg": f"JSON decode failed: {exc}",
                "type": "json_error",
            }],
        })
    return _dumps(tool_render_spec(spec, payload))


@mcp.tool()
def find_examples(query: str, k: int = 5) -> str:
    """Keyword search over tutorial / pattern / fixture examples.

    When: evidence for a draft (with schema_shape). Not a generator.
    """
    return _dumps(tool_find_examples(query, k=k))


@mcp.tool()
def id_registry(path: str) -> str:
    """Declared and unresolved cross-file IDs in a config folder.

    When: before drafting IDs into a file that lives in a tree.
    """
    return _dumps(tool_id_registry(path))


@mcp.tool()
def explain_diagnostic(rule_id: str) -> str:
    """Prose + fix hint for a gauntlet / conform rule id.

    When: after a failed gauntlet, before guessing a fix. Then re-validate.
    """
    return _dumps(tool_explain_diagnostic(rule_id))


@mcp.tool()
def open_config_folder(path: str) -> str:
    """Open an existing FEWS config (ledger: all files origin=human).

    When: first touch of an existing tree. Does not rewrite XML.
    """
    return _dumps(open_config(path))


@mcp.tool()
def list_patterns(query: str | None = None) -> str:
    """List farmed patterns (path, vars, outputs). Filter by keyword.

    When: do not use for new writes; use admit_file. Left registered
    for manual/legacy calls.
    """
    return _dumps(tool_list_patterns(query))


@mcp.tool()
def create_project(path: str, name: str | None = None) -> str:
    """Create a new project folder (project.yaml + state). No XML yet.

    When: do not use for new writes; use admit_file. Left registered
    for manual/legacy calls.
    """
    return _dumps(tool_create_project(path, name=name))


@mcp.tool()
def apply_slots(path: str, ops: str) -> str:
    """Apply slot ops as a JSON array: add_import, add_basin, set_variables, add_capability, remove.

    When: do not use for new writes; use admit_file. Left registered
    for manual/legacy calls.

    Example ops: [{"op":"add_import","name":"GFS"}]
    """
    return _dumps(tool_apply_slots(path, ops))


@mcp.tool()
def build_project(path: str, phase: str | None = None) -> str:
    """Expand patterns → Jinja → XSD into generated/. Optional phase: imports|process|model|visualize.

    When: do not use for new writes; use admit_file. Left registered
    for manual/legacy calls. Must not clobber origin=human or origin=llm.
    """
    return _dumps(tool_build_project(path, phase=phase))


@mcp.tool()
def admit_file(path: str, relpath: str, xml: str, spec: str | None = None) -> str:
    """Admit host-authored XML after xsd+conform. Marks origin=llm.

    When: write gate after validate_xml passes. Allowed even when a
    catalog name exists. Never invent a pattern.
    """
    return _dumps(tool_admit_file(path, relpath, xml, spec=spec))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
