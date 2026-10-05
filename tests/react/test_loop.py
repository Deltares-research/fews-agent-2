"""run_react: tool dispatch round-trip, parallel calls, guard stops."""
from __future__ import annotations

import json

from fews_agent.agent.providers.base import ToolCall, ToolSpec
from fews_agent.react.loop import run_react
from fews_agent.react.registry import Tool, ToolRegistry

from .conftest import StubProvider, final, tool_use


def _echo_registry() -> ToolRegistry:
    return ToolRegistry([
        Tool(
            spec=ToolSpec(name="echo", description="echo",
                          input_schema={"type": "object", "properties": {}}),
            handler=lambda c, a: {"echo": a},
        ),
    ])


def test_three_step_run(ctx):
    provider = StubProvider(script=[
        tool_use(ToolCall(id="a", name="echo", arguments={"n": 1})),
        tool_use(ToolCall(id="b", name="echo", arguments={"n": 2})),
        final("all done"),
    ])
    result = run_react(provider, "sys", "go", _echo_registry(), ctx)
    assert result.stopped == "final"
    assert result.final_text == "all done"
    assert result.iterations == 3
    # Transcript: user, assistant+call, tool, assistant+call, tool.
    tool_messages = [m for m in result.transcript if m.role == "tool"]
    assert [m.tool_call_id for m in tool_messages] == ["a", "b"]
    # Usage tallied per chat call.
    assert ctx.usage.llm_calls == 3
    assert ctx.usage.total() == 3 * 120


def test_parallel_tool_calls_each_get_a_message(ctx):
    provider = StubProvider(script=[
        tool_use(ToolCall(id="a", name="echo", arguments={"n": 1}),
                 ToolCall(id="b", name="echo", arguments={"n": 2})),
        final(),
    ])
    result = run_react(provider, "sys", "go", _echo_registry(), ctx)
    tool_messages = [m for m in result.transcript if m.role == "tool"]
    assert [m.tool_call_id for m in tool_messages] == ["a", "b"]
    assert json.loads(tool_messages[1].content) == {"echo": {"n": 2}}


def test_max_iterations_stop(ctx):
    looping = [tool_use(ToolCall(id=f"c{i}", name="echo", arguments={}))
               for i in range(10)]
    provider = StubProvider(script=looping)
    result = run_react(provider, "sys", "go", _echo_registry(), ctx,
                       max_iterations=3)
    assert result.stopped == "max_iterations"
    assert result.final_text is None
    assert result.iterations == 3


def test_token_budget_stop(ctx):
    provider = StubProvider(script=[
        tool_use(ToolCall(id="a", name="echo", arguments={})),
        tool_use(ToolCall(id="b", name="echo", arguments={})),
    ])
    # Each scripted response reports 120 tokens; budget trips before call 2.
    result = run_react(provider, "sys", "go", _echo_registry(), ctx,
                       token_budget=100)
    assert result.stopped == "token_budget"


def test_events_emitted(ctx):
    events: list[tuple[str, dict]] = []
    provider = StubProvider(script=[
        tool_use(ToolCall(id="a", name="echo", arguments={"n": 1})),
        final(),
    ])
    run_react(provider, "sys", "go", _echo_registry(), ctx,
              on_event=lambda kind, data: events.append((kind, data)))
    kinds = [k for k, _ in events]
    assert kinds == ["assistant", "tool_result", "assistant", "stop"]
