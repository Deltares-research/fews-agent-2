"""LangGraph engine for the ReAct agent (+ LangSmith tracing).

The native loop (`loop.py`) and this module are interchangeable
ENGINES over the same substrate: the ToolRegistry (with its
validate-don't-trust dispatch, error-as-JSON contract and result
clamp) and the ToolContext workspace are reused unchanged — LangGraph
replaces only the chat/dispatch iteration, via
`langgraph.prebuilt.create_react_agent`.

Model routing stays on LiteLLM (`langchain-litellm`'s ChatLiteLLM), so
the same `FEWS_AGENT_MODEL` strings (azure_ai/..., openai/...,
ollama/...) work for both engines.

LangSmith: tracing is pure configuration — set in the environment
(.env works):

    LANGSMITH_TRACING=true
    LANGSMITH_API_KEY=lsv2_...
    LANGSMITH_PROJECT=fews-react        (optional; defaults to "default")

Every agent step, tool call (name + args + result), token count and
latency then lands in the LangSmith project automatically; no code
here references langsmith directly.
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Callable

import litellm

from fews_agent.agent.providers.base import ToolCall

from .context import ToolContext
from .loop import OnEvent, ReactResult, _emit
from .registry import ToolRegistry

# Same rationale as providers/litellm_provider.py: Azure reasoning-tier
# models reject non-default sampling params server-side.
litellm.drop_params = True


def langsmith_status() -> str:
    """Human-readable tracing status for the runner banner."""
    if os.environ.get("LANGSMITH_TRACING", "").lower() in ("1", "true"):
        if os.environ.get("LANGSMITH_API_KEY"):
            return ("on (project="
                    + os.environ.get("LANGSMITH_PROJECT", "default") + ")")
        return "requested but LANGSMITH_API_KEY is missing"
    return "off (set LANGSMITH_TRACING=true + LANGSMITH_API_KEY)"


def to_langchain_tools(registry: ToolRegistry, ctx: ToolContext) -> list:
    """Wrap every registry tool as a LangChain StructuredTool.

    The wrapper funnels back through `registry.dispatch`, so the
    JSON-result contract, error encoding and 20 KB clamp hold under
    both engines — and LangSmith traces show the exact same payloads
    the model sees.
    """
    from langchain_core.tools import StructuredTool

    def make_func(name: str) -> Callable[..., str]:
        def call(**kwargs: Any) -> str:
            tc = ToolCall(id=f"call_{uuid.uuid4().hex[:12]}",
                          name=name, arguments=kwargs)
            return registry.dispatch(ctx, tc).content
        return call

    tools = []
    for tool in registry.tools():
        tools.append(StructuredTool(
            name=tool.spec.name,
            description=tool.spec.description,
            args_schema=tool.spec.input_schema,  # plain JSON schema dict
            func=make_func(tool.spec.name),
        ))
    return tools


def _text(message: Any) -> str:
    """Message text across langchain-core versions.

    1.x returns a ``TextAccessor`` — a str subclass that is ALSO
    callable for 0.x back-compat (and warns when called), so check for
    str before callable."""
    value = message.text
    if isinstance(value, str):
        return str(value)
    return value() if callable(value) else ""


def _usage_from_message(message: Any) -> dict[str, int] | None:
    meta = getattr(message, "usage_metadata", None)
    if not meta:
        return None
    return {
        "prompt_tokens": int(meta.get("input_tokens", 0) or 0),
        "completion_tokens": int(meta.get("output_tokens", 0) or 0),
    }


class ReactSession:
    """A persistent multi-turn agent session on LangGraph.

    The graph is checkpointed in memory under one thread id, so a
    second ``send()`` continues the SAME conversation — the model sees
    the full prior transcript, and the shared ToolContext keeps every
    rendered file (with its Pydantic model) alive. This is how a user
    instructs changes to an already-built config: build on turn 1,
    "change X" on turn 2, same session.
    """

    def __init__(
        self,
        chat_model: Any,
        registry: ToolRegistry,
        ctx: ToolContext,
        system: str,
        max_iterations: int = 60,
        on_event: OnEvent | None = None,
    ) -> None:
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.prebuilt import create_react_agent

        self.ctx = ctx
        self.max_iterations = max_iterations
        self.on_event = on_event
        self._agent = create_react_agent(
            chat_model, to_langchain_tools(registry, ctx), prompt=system,
            checkpointer=InMemorySaver())
        self._config = {
            "configurable": {"thread_id": "react"},
            "recursion_limit": 2 * max_iterations + 1,
        }

    def send(self, user_text: str) -> ReactResult:
        """Run one user turn to completion (final answer or guard)."""
        from langgraph.errors import GraphRecursionError

        iterations = 0
        final_text: str | None = None
        stopped = "final"
        try:
            for update in self._agent.stream(
                {"messages": [("user", user_text)]},
                config=self._config,
                stream_mode="updates",
            ):
                for node, payload in update.items():
                    for message in (payload or {}).get("messages", []):
                        kind = type(message).__name__
                        if kind == "AIMessage":
                            iterations += 1
                            self.ctx.usage.add(_usage_from_message(message))
                            # Keep the id: parallel tool results come
                            # back in COMPLETION order, so a transcript
                            # can only pair call->result by id.
                            calls = [{"id": c.get("id"),
                                      "name": c.get("name"),
                                      "arguments": c.get("args")}
                                     for c in (message.tool_calls or [])]
                            _emit(self.on_event, "assistant", {
                                "iteration": iterations,
                                "text": _text(message) or None,
                                "tool_calls": calls,
                                "usage": _usage_from_message(message),
                            })
                            if not message.tool_calls:
                                final_text = _text(message) or None
                        elif kind == "ToolMessage":
                            _emit(self.on_event, "tool_result", {
                                "name": message.name,
                                "tool_call_id": message.tool_call_id,
                                "content": _text(message),
                            })
        except GraphRecursionError:
            stopped = "max_iterations"

        if stopped == "final" and final_text is None:
            stopped = "max_iterations"  # ended without a final answer
        _emit(self.on_event, "stop", {"reason": stopped})
        return ReactResult(final_text, iterations, self.ctx.usage, [],
                           stopped=stopped)


def run_react_lg(
    chat_model: Any,
    system: str,
    user_prompt: str,
    registry: ToolRegistry,
    ctx: ToolContext,
    max_iterations: int = 60,
    on_event: OnEvent | None = None,
) -> ReactResult:
    """One-shot convenience wrapper over ReactSession (single turn).

    Emits the same on_event stream as the native loop ("assistant" /
    "tool_result" / "stop"), so the runner's console lines and
    react_log.jsonl are engine-independent. ``max_iterations`` maps to
    the graph recursion limit (one iteration = agent step + tool step).
    """
    session = ReactSession(chat_model, registry, ctx, system,
                           max_iterations=max_iterations,
                           on_event=on_event)
    return session.send(user_prompt)


def default_chat_model(model: str) -> Any:
    """ChatLiteLLM over the same model string the native engine uses.

    ``max_retries`` rides out transient 429s — a long agent run burns
    enough tokens to trip per-minute Azure quotas mid-flight, and one
    rate-limit must not kill an otherwise-healthy 20-iteration run.
    """
    from langchain_litellm import ChatLiteLLM

    return ChatLiteLLM(model=model, max_retries=6)
