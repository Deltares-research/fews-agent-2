"""The ReAct loop: chat -> dispatch tool calls -> repeat until final.

Provider-agnostic over `providers.base.Provider.chat(...)`. The loop
never prints — progress flows through the ``on_event`` callback so the
runner owns all I/O (console + ``react_log.jsonl``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from fews_agent.agent.providers.base import Message, Provider

from .context import ToolContext, UsageTally
from .registry import ToolRegistry

OnEvent = Callable[[str, dict[str, Any]], None]

Stopped = Literal["final", "max_iterations", "token_budget"]


@dataclass
class ReactResult:
    final_text: str | None
    iterations: int
    usage: UsageTally
    transcript: list[Message] = field(default_factory=list)
    stopped: Stopped = "final"


def _emit(on_event: OnEvent | None, kind: str, data: dict[str, Any]) -> None:
    if on_event is None:
        return
    try:
        on_event(kind, data)
    except Exception:  # noqa: BLE001 — observer must not kill the loop
        pass


def run_react(
    provider: Provider,
    system: str,
    user_prompt: str,
    registry: ToolRegistry,
    ctx: ToolContext,
    max_iterations: int = 60,
    token_budget: int = 1_500_000,
    on_event: OnEvent | None = None,
) -> ReactResult:
    """Run the loop until the model stops calling tools, or a guard trips.

    Every tool call in a response gets a tool message back (Azure/GPT
    emits parallel calls; an unanswered ``tool_call_id`` 400s the next
    OpenAI-shaped request). A non-``"final"`` stop is a failure the
    caller must surface loudly.
    """
    messages: list[Message] = [Message(role="user", content=user_prompt)]
    iterations = 0

    while True:
        if iterations >= max_iterations:
            _emit(on_event, "stop", {"reason": "max_iterations"})
            return ReactResult(None, iterations, ctx.usage, messages,
                               stopped="max_iterations")
        if ctx.usage.total() >= token_budget:
            _emit(on_event, "stop", {"reason": "token_budget",
                                     "tokens": ctx.usage.total()})
            return ReactResult(None, iterations, ctx.usage, messages,
                               stopped="token_budget")
        iterations += 1

        resp = provider.chat(system, messages, registry.specs(),
                             tool_choice="auto")
        ctx.usage.add(resp.usage)
        _emit(on_event, "assistant", {
            "iteration": iterations,
            "text": resp.text,
            "tool_calls": [{"id": c.id, "name": c.name,
                            "arguments": c.arguments}
                           for c in resp.tool_calls],
            "usage": resp.usage,
        })

        if resp.stop_reason != "tool_use" or not resp.tool_calls:
            _emit(on_event, "stop", {"reason": "final"})
            return ReactResult(resp.text, iterations, ctx.usage, messages,
                               stopped="final")

        messages.append(Message(role="assistant", content=resp.text or "",
                                tool_calls=resp.tool_calls))
        for call in resp.tool_calls:
            result = registry.dispatch(ctx, call)
            _emit(on_event, "tool_result", {
                "name": call.name,
                "tool_call_id": call.id,
                "content": result.content,
            })
            messages.append(Message(role="tool", content=result.content,
                                    tool_call_id=call.id))
