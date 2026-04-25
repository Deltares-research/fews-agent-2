"""Anthropic backend.

Claude handles OpenAI-style tool calls natively via its own shape:
`tools=[{"name","description","input_schema"}]` at the request level and
`content=[{"type":"tool_use","id":...,"name":...,"input":...}, ...]`
in the response. We map in both directions to the provider-agnostic
`ToolSpec` / `ToolCall` / `ToolResult` dataclasses.

Defaults to `claude-haiku-4-5` (cheap, fast, strong at tool loops).
Reads `ANTHROPIC_API_KEY` from the environment (loaded via
`python-dotenv` at TUI startup).
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Literal

from anthropic import Anthropic

from .base import (
    Message,
    ProviderResponse,
    ToolCall,
    ToolSpec,
)

_logger = logging.getLogger(__name__)


class AnthropicProvider:
    """Anthropic Claude backend."""

    def __init__(self, model: str = "claude-haiku-4-5") -> None:
        self.model = model
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            _logger.warning(
                "ANTHROPIC_API_KEY not set; AnthropicProvider will fail on first call"
            )
        self._client = Anthropic(api_key=api_key) if api_key else Anthropic()

    def chat(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        tool_choice: Literal["auto", "required", "none"] = "auto",
    ) -> ProviderResponse:
        anth_messages = self._to_anthropic_messages(messages)
        anth_tools = [self._to_anthropic_tool(t) for t in tools]

        resp = self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=anth_messages,
            tools=anth_tools or None,
            tool_choice={"type": tool_choice} if tool_choice != "auto" else {"type": "auto"},
        )

        calls: list[ToolCall] = []
        text_parts: list[str] = []
        thinking_parts: list[str] = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "tool_use":
                calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=dict(block.input or {}),
                    )
                )
            elif btype == "text":
                text_parts.append(block.text)
            elif btype == "thinking":
                # Extended-thinking content; Claude only emits this when
                # the request opted in via thinking={...}. Capture it for
                # the replay log.
                thinking_parts.append(getattr(block, "thinking", "") or "")

        usage_obj = getattr(resp, "usage", None)
        usage: dict[str, int] | None = None
        if usage_obj is not None:
            prompt_tokens = getattr(usage_obj, "input_tokens", 0) or 0
            completion_tokens = getattr(usage_obj, "output_tokens", 0) or 0
            usage = {
                "prompt_tokens": int(prompt_tokens),
                "completion_tokens": int(completion_tokens),
                "total_tokens": int(prompt_tokens + completion_tokens),
            }

        return ProviderResponse(
            text="\n".join(text_parts).strip() or None,
            tool_calls=calls,
            stop_reason=resp.stop_reason or ("tool_use" if calls else "end_turn"),
            usage=usage,
            thinking="\n\n".join(thinking_parts).strip() or None,
        )

    @staticmethod
    def _to_anthropic_tool(tool: ToolSpec) -> dict[str, Any]:
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }

    @staticmethod
    def _to_anthropic_messages(messages: list[Message]) -> list[dict[str, Any]]:
        """Translate our flat Message list into Anthropic's block form.

        Assistant messages with tool_calls become a single assistant
        message with a list of `tool_use` content blocks. Tool-role
        messages become user messages with `tool_result` blocks so
        Claude can tie results back to the originating call.
        """
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                continue  # system is a top-level arg in Anthropic's API
            if m.role == "assistant":
                content: list[dict[str, Any]] = []
                if m.content:
                    content.append({"type": "text", "text": m.content})
                for c in m.tool_calls or []:
                    content.append(
                        {
                            "type": "tool_use",
                            "id": c.id,
                            "name": c.name,
                            "input": c.arguments,
                        }
                    )
                if not content:
                    content = [{"type": "text", "text": ""}]
                out.append({"role": "assistant", "content": content})
            elif m.role == "tool":
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.tool_call_id or f"tu_{uuid.uuid4().hex[:12]}",
                                "content": m.content,
                            }
                        ],
                    }
                )
            else:  # user
                out.append({"role": "user", "content": m.content})
        return out
