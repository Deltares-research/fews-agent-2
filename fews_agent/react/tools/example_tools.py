"""Reference-example tool: ground file CONTENT in a real working config.

XSD + cross-reference validation prove a file is well-formed, not that
it will move data (the first live GFS run produced a folder import with
a NetCDF-flavoured idMap — valid, inert). The reference config
(`examples/generated-config-tutorial/`, a real working FEWS setup)
encodes the content conventions the schemas don't: which importType
pairs with which idMap style, what a topology workflow node carries,
retrieval patterns, descriptor attributes. This tool lets the agent
read it before writing an unfamiliar file type.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fews_agent.agent.providers.base import ToolSpec

from ..context import ToolContext
from ..registry import Tool

EXAMPLES_ROOT = (Path(__file__).resolve().parents[3]
                 / "examples" / "generated-config-tutorial")

MAX_EXAMPLE_CHARS = 12_000


def _listing(needle: str) -> list[str]:
    rows = []
    for p in sorted(EXAMPLES_ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(EXAMPLES_ROOT).as_posix()
        if needle and needle not in rel.lower():
            continue
        rows.append(rel)
    return rows


def _read_example(ctx: ToolContext, args: dict[str, Any]) -> Any:
    if not EXAMPLES_ROOT.is_dir():
        return {"error": "reference config not present on this checkout"}
    path = str(args.get("path") or "").replace("\\", "/").strip()
    if not path:
        rows = _listing(str(args.get("filter") or "").lower())
        return {"count": len(rows), "files": "\n".join(rows)}
    target = (EXAMPLES_ROOT / path).resolve()
    if EXAMPLES_ROOT.resolve() not in target.parents:
        return {"error": "path must be relative, inside the reference "
                         "config"}
    if not target.is_file():
        close = _listing(Path(path).name.lower())
        return {"error": f"no such reference file: {path}"
                + (f"; close: {close[:8]}" if close else "")}
    content = target.read_text(encoding="utf-8", errors="replace")
    out: dict[str, Any] = {"path": path,
                           "content": content[:MAX_EXAMPLE_CHARS]}
    if len(content) > MAX_EXAMPLE_CHARS:
        out["truncated_chars"] = len(content) - MAX_EXAMPLE_CHARS
    return out


READ_EXAMPLE = Tool(
    spec=ToolSpec(
        name="read_example",
        description=(
            "Read a file from the bundled REFERENCE FEWS config (a real, "
            "working setup). Call with filter (no path) to list matching "
            "reference files; with path to fetch one. Before writing an "
            "unfamiliar file type, read the closest reference example — "
            "it shows the content conventions schemas don't encode "
            "(importType<->idMap pairing, serverUrl-based retrieval, "
            "topology workflow nodes, descriptor attributes). Imitate "
            "its conventions, not its project-specific values."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string",
                         "description": "reference-relative path from a "
                                        "previous listing"},
                "filter": {"type": "string",
                           "description": "case-insensitive substring to "
                                          "list matching reference files"},
            },
            "additionalProperties": False,
        },
    ),
    handler=_read_example,
)
