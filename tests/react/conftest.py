"""Fixtures for the ReAct prototype: a scripted StubProvider (no model,
no network) and a tmp ToolContext."""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from fews_agent.agent.providers.base import (
    Message,
    ProviderResponse,
    ToolSpec,
)
from fews_agent.react.context import ToolContext


@dataclass
class StubProvider:
    """Satisfies the Provider protocol with a pre-scripted response list."""

    script: list[ProviderResponse]
    model: str = "stub"
    calls: list[dict] = field(default_factory=list)

    def chat(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        tool_choice: str = "auto",
    ) -> ProviderResponse:
        self.calls.append({
            "system": system,
            "messages": list(messages),
            "tools": [t.name for t in tools],
        })
        if not self.script:
            raise AssertionError("StubProvider script exhausted")
        return self.script.pop(0)


def tool_use(*calls) -> ProviderResponse:
    return ProviderResponse(
        text=None, tool_calls=list(calls), stop_reason="tool_use",
        usage={"prompt_tokens": 100, "completion_tokens": 20},
    )


def final(text: str = "done") -> ProviderResponse:
    return ProviderResponse(
        text=text, tool_calls=[], stop_reason="end_turn",
        usage={"prompt_tokens": 100, "completion_tokens": 20},
    )


@pytest.fixture
def ctx(tmp_path) -> ToolContext:
    return ToolContext.for_session(tmp_path / "session")
