"""ToolRegistry dispatch contract: JSON results, encoded errors, clamp."""
from __future__ import annotations

import json

import pytest

from fews_agent.agent.providers.base import ToolCall, ToolSpec
from fews_agent.react.registry import MAX_RESULT_CHARS, Tool, ToolRegistry


def _tool(name: str, handler) -> Tool:
    return Tool(
        spec=ToolSpec(name=name, description=name,
                      input_schema={"type": "object", "properties": {}}),
        handler=handler,
    )


def test_dispatch_success_json(ctx):
    reg = ToolRegistry([_tool("echo", lambda c, a: {"got": a})])
    result = reg.dispatch(ctx, ToolCall(id="c1", name="echo",
                                        arguments={"x": 1}))
    assert result.tool_call_id == "c1"
    assert json.loads(result.content) == {"got": {"x": 1}}
    assert ctx.usage.tool_calls == 1


def test_handler_exception_encoded_not_raised(ctx):
    def boom(c, a):
        raise ValueError("kaput")

    reg = ToolRegistry([_tool("boom", boom)])
    result = reg.dispatch(ctx, ToolCall(id="c1", name="boom", arguments={}))
    data = json.loads(result.content)
    assert "ValueError: kaput" in data["error"]


def test_unknown_tool_encoded(ctx):
    reg = ToolRegistry([_tool("echo", lambda c, a: {})])
    result = reg.dispatch(ctx, ToolCall(id="c1", name="nope", arguments={}))
    data = json.loads(result.content)
    assert "unknown tool" in data["error"]
    assert "echo" in data["error"]


def test_duplicate_registration_raises():
    with pytest.raises(ValueError, match="duplicate"):
        ToolRegistry([_tool("a", lambda c, x: {}),
                      _tool("a", lambda c, x: {})])


def test_result_clamped(ctx):
    reg = ToolRegistry([_tool("big", lambda c, a: {"blob": "x" * 50_000})])
    result = reg.dispatch(ctx, ToolCall(id="c1", name="big", arguments={}))
    assert len(result.content) <= MAX_RESULT_CHARS
    assert "truncated" in result.content
