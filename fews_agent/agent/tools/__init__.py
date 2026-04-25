"""Tools the LLM can call, plus the dispatcher the agent loop uses.

Every tool is a pure function of `(ctx, **args) -> dict`. Each is
exported as a `ToolSpec` (JSON schema the provider advertises to the
model) and registered in `TOOLS` / `HANDLERS`. The dispatcher looks up
the handler by name, calls it, JSON-serializes the return, and packages
it into a `ToolResult`.

Errors don't raise — the handler returns `{"error": "..."}` so the
model sees the failure and can correct. A thrown exception is still
caught here as a last-resort fallback.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from ..providers.base import ToolResult, ToolSpec
from . import generate_tool, project_tools, spec_tools


@dataclass
class ToolContext:
    """Shared state the tool handlers mutate/read."""

    store: Any  # ProjectStore (avoid import cycle)
    project_name: str
    spec_name: str
    project_data: dict[str, Any] = field(default_factory=dict)
    last_xml: str | None = None
    last_xsd_ok: bool | None = None
    last_xsd_msg: str | None = None


HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "list_specs": spec_tools.list_specs,
    "describe_spec": spec_tools.describe_spec,
    "generate": generate_tool.generate,
    "set_geodatum": project_tools.set_geodatum,
    "upsert_location": project_tools.upsert_location,
    "remove_location": project_tools.remove_location,
    "list_projects": project_tools.list_projects,
    "save_project": project_tools.save_project,
}


TOOLS: list[ToolSpec] = [
    spec_tools.LIST_SPECS_TOOL,
    spec_tools.DESCRIBE_SPEC_TOOL,
    generate_tool.GENERATE_TOOL,
    project_tools.SET_GEODATUM_TOOL,
    project_tools.UPSERT_LOCATION_TOOL,
    project_tools.REMOVE_LOCATION_TOOL,
    project_tools.LIST_PROJECTS_TOOL,
    project_tools.SAVE_PROJECT_TOOL,
]


def dispatch(tool_call_id: str, name: str, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Look up the handler, run it, serialize the return."""
    handler = HANDLERS.get(name)
    if handler is None:
        payload = {"error": f"unknown tool: {name!r}"}
    else:
        try:
            payload = handler(ctx=ctx, **args)
        except TypeError as exc:
            payload = {"error": f"bad arguments to {name}: {exc}"}
        except Exception as exc:
            payload = {"error": f"{type(exc).__name__}: {exc}"}
    return ToolResult(
        tool_call_id=tool_call_id,
        content=json.dumps(payload, default=_json_default, ensure_ascii=False),
    )


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Not JSON-serializable: {type(obj).__name__}")


__all__ = ["ToolContext", "TOOLS", "HANDLERS", "dispatch"]
