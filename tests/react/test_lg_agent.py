"""LangGraph engine: tool conversion + a scripted graph run (no model,
no network)."""
from __future__ import annotations

import json
from typing import Any

import pytest

langchain_core = pytest.importorskip("langchain_core")
pytest.importorskip("langgraph")

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from fews_agent.agent.providers.base import ToolSpec
from fews_agent.react.lg_agent import run_react_lg, to_langchain_tools
from fews_agent.react.registry import Tool, ToolRegistry


def _echo_registry(record: list) -> ToolRegistry:
    def echo(ctx, a):
        record.append(a)
        return {"echo": a}

    def boom(ctx, a):
        raise ValueError("kaput")

    schema = {"type": "object",
              "properties": {"n": {"type": "integer"}},
              "additionalProperties": False}
    return ToolRegistry([
        Tool(spec=ToolSpec(name="echo", description="echo back",
                           input_schema=schema), handler=echo),
        Tool(spec=ToolSpec(name="boom", description="always fails",
                           input_schema=schema), handler=boom),
    ])


class ScriptedChatModel(BaseChatModel):
    """Returns pre-scripted AIMessages in order; bind_tools records the
    advertised tools and returns self (standard fake-model pattern)."""

    script: list[AIMessage]
    bound_tool_names: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any):
        self.bound_tool_names = [t.name for t in tools]
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        message = self.script.pop(0)
        return ChatResult(generations=[ChatGeneration(message=message)])


def test_to_langchain_tools_roundtrip(ctx):
    record: list = []
    registry = _echo_registry(record)
    tools = to_langchain_tools(registry, ctx)
    by_name = {t.name: t for t in tools}
    assert set(by_name) == {"echo", "boom"}
    assert by_name["echo"].description == "echo back"
    assert by_name["echo"].args_schema["properties"]["n"]["type"] == "integer"
    out = by_name["echo"].func(n=7)
    assert json.loads(out) == {"echo": {"n": 7}}
    assert record == [{"n": 7}]
    # Handler exceptions keep the error-as-JSON contract.
    err = json.loads(by_name["boom"].func(n=1))
    assert "ValueError: kaput" in err["error"]


def test_run_react_lg_scripted(ctx):
    record: list = []
    registry = _echo_registry(record)
    model = ScriptedChatModel(script=[
        AIMessage(content="", tool_calls=[
            {"name": "echo", "args": {"n": 1}, "id": "a"},
            {"name": "echo", "args": {"n": 2}, "id": "b"},
        ]),
        AIMessage(content="all done"),
    ])
    events: list[tuple[str, dict]] = []
    result = run_react_lg(model, "sys", "go", registry, ctx,
                          on_event=lambda k, d: events.append((k, d)))
    assert result.stopped == "final"
    assert result.final_text == "all done"
    assert record == [{"n": 1}, {"n": 2}]  # parallel calls both ran
    kinds = [k for k, _ in events]
    assert kinds == ["assistant", "tool_result", "tool_result",
                     "assistant", "stop"]
    assert model.bound_tool_names == ["echo", "boom"]


def test_react_session_multi_turn_same_context(ctx):
    """Turn 2 continues the SAME conversation (full prior transcript)
    and mutates the same workspace — the 'user instructs a change'
    flow."""
    from fews_agent.react.lg_agent import ReactSession

    record: list = []
    registry = _echo_registry(record)

    class CountingModel(ScriptedChatModel):
        seen_message_counts: list[int] = []

        def _generate(self, messages, stop=None, run_manager=None,
                      **kwargs):
            self.seen_message_counts.append(len(messages))
            return super()._generate(messages, stop=stop,
                                     run_manager=run_manager, **kwargs)

    model = CountingModel(script=[
        # Turn 1: one tool call, then final.
        AIMessage(content="", tool_calls=[
            {"name": "echo", "args": {"n": 1}, "id": "a"}]),
        AIMessage(content="built"),
        # Turn 2: edit via another tool call, then final.
        AIMessage(content="", tool_calls=[
            {"name": "echo", "args": {"n": 2}, "id": "b"}]),
        AIMessage(content="changed"),
    ])
    session = ReactSession(model, registry, ctx, "sys")
    first = session.send("build it")
    assert first.final_text == "built"
    second = session.send("now change it")
    assert second.final_text == "changed"
    assert record == [{"n": 1}, {"n": 2}]  # same registry/ctx both turns
    # The checkpointer carries the transcript across turns: turn-2's
    # first model call must see MORE messages than turn-1's final call
    # (system+user+ai+tool+ai, plus the new user message).
    counts = model.seen_message_counts
    assert counts[2] > counts[1], counts


def test_run_react_lg_recursion_stop(ctx):
    record: list = []
    registry = _echo_registry(record)
    looping = [AIMessage(content="", tool_calls=[
        {"name": "echo", "args": {"n": i}, "id": f"c{i}"}])
        for i in range(20)]
    model = ScriptedChatModel(script=looping)
    result = run_react_lg(model, "sys", "go", registry, ctx,
                          max_iterations=3)
    # The prebuilt agent may emit a synthetic "need more steps" final
    # message before the recursion guard raises; the stop reason is
    # what the runner keys exit codes off.
    assert result.stopped == "max_iterations"
