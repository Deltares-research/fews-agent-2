"""Tool registry: name -> (ToolSpec, handler) with JSON-safe dispatch.

The dispatch contract matches `providers.base.ToolResult`: errors are
encoded as ``{"error": "..."}`` JSON in the result content, never
raised, so the model can inspect and correct. The ReAct loop IS the
repair loop.
"""
from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Sequence

from fews_agent.agent.providers.base import ToolCall, ToolResult, ToolSpec

from .context import ToolContext

# A tool result larger than this is clamped — verbose results are the
# main context-growth risk (see plan §7). Error texts fit comfortably.
MAX_RESULT_CHARS = 20_000

ToolHandler = Callable[[ToolContext, dict[str, Any]], Any]


@dataclass(frozen=True)
class Tool:
    """One registered tool: the spec the model sees + the handler."""

    spec: ToolSpec
    handler: ToolHandler


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return value.as_posix()
    return str(value)


class ToolRegistry:
    def __init__(self, tools: Sequence[Tool]) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            if tool.spec.name in self._tools:
                raise ValueError(f"duplicate tool name: {tool.spec.name!r}")
            self._tools[tool.spec.name] = tool

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def tools(self) -> list[Tool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools)

    def dispatch(self, ctx: ToolContext, call: ToolCall) -> ToolResult:
        ctx.usage.tool_calls += 1
        tool = self._tools.get(call.name)
        if tool is None:
            payload: Any = {
                "error": f"unknown tool {call.name!r}; "
                f"available: {', '.join(self._tools)}"
            }
        else:
            try:
                payload = tool.handler(ctx, call.arguments or {})
            except Exception as exc:  # noqa: BLE001 — encoded, never raised
                payload = {
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(limit=5),
                }
        # Compact separators: every result char is re-sent to the model
        # in EVERY subsequent loop iteration, so encoding overhead
        # compounds quadratically over a run.
        content = json.dumps(payload, separators=(",", ":"),
                             default=_json_default)
        if len(content) > MAX_RESULT_CHARS:
            tail = f'...[truncated {len(content) - MAX_RESULT_CHARS} chars]"'
            content = content[: MAX_RESULT_CHARS - len(tail)] + tail
        return ToolResult(tool_call_id=call.id, content=content)
