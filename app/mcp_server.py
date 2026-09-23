"""MCP server — verification toolbelt + optional session generation.

Local hosts (Cursor, VS Code Copilot, Claude Desktop) call these tools
over STDIO. Validation logic lives in ``fews_agent.validation.toolbelt``;
this module only serializes JSON.

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
from fews_agent.validation.toolbelt import (
    tool_conform_lint,
    tool_conform_lint_xml,
    tool_explain_diagnostic,
    tool_find_examples,
    tool_id_registry,
    tool_schema_shape,
    tool_validate_config,
    tool_validate_xml,
)

mcp = FastMCP(
    "fews-agent",
    instructions=(
        "Delft-FEWS verification harness. You (the host LLM) author XML; "
        "these tools check it. Typical workflow on an EXISTING config:\n"
        "1. validate_config(path) or open_config(path) on the user's folder.\n"
        "2. schema_shape(spec) + find_examples(query) before writing a file.\n"
        "3. validate_xml(xml) on a draft, then repair from diagnostics.\n"
        "4. id_registry(path) to reuse IDs already declared in the tree.\n"
        "Do not invent parameterId / moduleInstanceId / idMapId values.\n"
        "Path tools need a folder on THIS machine. Remote chatbots should "
        "use the HTTP API's POST /validate/xml instead."
    ),
)


def _dumps(payload: dict) -> str:
    return json.dumps(payload, indent=2, default=str)


@mcp.tool()
def validate_config(path: str, tiers: str | None = None) -> str:
    """Run XSD + semantic + conform + FEWS check on a config folder.

    Args:
        path: Absolute path to a FEWS config tree.
        tiers: Optional comma-separated subset: xsd,semantic,conform,fews_check.
    """
    parsed = [t.strip() for t in tiers.split(",")] if tiers else None
    return _dumps(tool_validate_config(path, tiers=parsed))


@mcp.tool()
def validate_xml(xml: str, spec: str | None = None) -> str:
    """Validate a pasted FEWS XML snippet against the pinned XSD (+ conform)."""
    return _dumps(tool_validate_xml(xml, spec=spec))


@mcp.tool()
def conform_lint(path: str) -> str:
    """FEWS-Conform naming lint on a config folder."""
    return _dumps(tool_conform_lint(path))


@mcp.tool()
def conform_lint_xml(xml: str, spec: str | None = None) -> str:
    """FEWS-Conform lint on a pasted snippet (remote-safe)."""
    return _dumps(tool_conform_lint_xml(xml, spec=spec))


@mcp.tool()
def schema_shape(spec: str) -> str:
    """Pinned Pydantic/XSD shape for a spec (e.g. TimeSeriesImportRun)."""
    return _dumps(tool_schema_shape(spec))


@mcp.tool()
def find_examples(query: str, k: int = 5) -> str:
    """Keyword search over tutorial / pattern / fixture examples."""
    return _dumps(tool_find_examples(query, k=k))


@mcp.tool()
def id_registry(path: str) -> str:
    """Declared and unresolved cross-file IDs in a config folder."""
    return _dumps(tool_id_registry(path))


@mcp.tool()
def explain_diagnostic(rule_id: str) -> str:
    """Prose + fix hint for a gauntlet / conform rule id."""
    return _dumps(tool_explain_diagnostic(rule_id))


@mcp.tool()
def open_config_folder(path: str) -> str:
    """Open an existing FEWS config (ledger: all files origin=human)."""
    return _dumps(open_config(path))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
