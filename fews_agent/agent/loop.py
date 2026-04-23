"""Agent chat loop — one user message in, one assistant reply out.

A turn is:
  1. Append the user message.
  2. Ask the provider (system prompt rebuilt fresh each turn).
  3. If the response has tool calls, dispatch each, append the results,
     ask again. Loop until the provider returns plain text or we hit
     `max_tool_rounds`.
  4. Return the final text.

Every mutating tool (upsert_location, remove_location, generate) writes
through `ProjectStore.save` synchronously inside its handler, so the
agent's `project_data` stays in step with the disk. The TUI reloads
from disk before each render to catch wizard-driven changes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..db import ProjectStore
from .prompts import build_system_prompt
from .providers.base import Message, Provider, ToolCall
from .tools import TOOLS, ToolContext, dispatch

_logger = logging.getLogger(__name__)


@dataclass
class AgentLoop:
    provider: Provider
    store: ProjectStore
    project_name: str
    spec_name: str = "locations"
    max_tool_rounds: int = 8

    messages: list[Message] = field(default_factory=list)
    ctx: ToolContext | None = None

    def __post_init__(self) -> None:
        data = self.store.load(self.project_name)
        self.ctx = ToolContext(
            store=self.store,
            project_name=self.project_name,
            spec_name=self.spec_name,
            project_data=data,
        )

    # ------------------------------------------------------------------
    # Public API

    def reload(self) -> None:
        """Re-sync the agent's in-memory project_data from disk.

        Called by the TUI after any wizard turn so the chat's view of
        state matches what the wizard just wrote.
        """
        assert self.ctx is not None
        self.ctx.project_data = self.store.load(self.project_name)

    def project_data(self) -> dict[str, Any]:
        assert self.ctx is not None
        return self.ctx.project_data

    def last_xml(self) -> str | None:
        assert self.ctx is not None
        return self.ctx.last_xml

    def turn(self, user_msg: str) -> str:
        """One conversational turn. Returns the assistant's final text."""
        assert self.ctx is not None
        self.messages.append(Message(role="user", content=user_msg))
        self.store.append_message(
            self.project_name, {"role": "user", "content": user_msg}
        )

        for round_idx in range(self.max_tool_rounds):
            system = build_system_prompt(self.spec_name, self.ctx.project_data)
            resp = self.provider.chat(
                system=system,
                messages=self.messages,
                tools=TOOLS,
                tool_choice="auto",
            )

            # Record the assistant turn (text + any tool calls) so the
            # provider can pick up where it left off on the next round.
            assistant_msg = Message(
                role="assistant",
                content=resp.text or "",
                tool_calls=list(resp.tool_calls),
            )
            self.messages.append(assistant_msg)

            if not resp.tool_calls:
                final = resp.text or ""
                self.store.append_message(
                    self.project_name, {"role": "assistant", "content": final}
                )
                return final

            # Run each tool, feed the results back.
            for call in resp.tool_calls:
                self._log_call(call)
                result = dispatch(call.id, call.name, call.arguments, self.ctx)
                self.messages.append(
                    Message(
                        role="tool",
                        content=result.content,
                        tool_call_id=result.tool_call_id,
                    )
                )

        # Hit the round cap without the model settling — surface that.
        cap_msg = (
            f"(reached tool-round cap of {self.max_tool_rounds}; "
            "last tool results are in project state)"
        )
        self.store.append_message(
            self.project_name, {"role": "assistant", "content": cap_msg}
        )
        return cap_msg

    # ------------------------------------------------------------------

    def _log_call(self, call: ToolCall) -> None:
        short_args = str(call.arguments)
        if len(short_args) > 200:
            short_args = short_args[:200] + "..."
        _logger.info("tool: %s(%s)", call.name, short_args)
