"""Provider-agnostic types for the agent loop.

Every backend (Ollama, Anthropic, OpenAI, Gemini) normalizes its native
request/response shape into these types so the agent loop and the tool
dispatcher don't know which provider they're talking to.

Two Protocols are defined:

- `Provider.chat(...)` — the standard loop. System prompt + message
  history + tool specs → response with either text or tool_calls.
  Assumes the model supports OpenAI-style tool calling (Claude, GPT,
  recent Qwen/Llama via Ollama).

- `StructuredOutputProvider.generate_json(...)` — the fallback for
  models that can't reliably tool-call (phi3.5, tinyllama). The agent
  loop can downgrade to "one shot, produce JSON matching this schema,
  we'll call the tool ourselves" when the primary path fails.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ToolCall:
    """Provider-normalized tool call from the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """Result we hand back to the model for a given tool_call_id.

    `content` is the JSON-serialized return value of the tool handler;
    errors are encoded as `{"error": "..."}` in the JSON, not raised,
    so the model can inspect and correct.
    """

    tool_call_id: str
    content: str


@dataclass
class Message:
    """One turn in the conversation."""

    role: Role
    content: str = ""
    # On assistant messages that called tools:
    tool_calls: list[ToolCall] = field(default_factory=list)
    # On tool-role messages:
    tool_call_id: str | None = None


@dataclass
class ToolSpec:
    """Declaration the provider advertises to the model.

    `input_schema` is a JSON Schema object. Anthropic and OpenAI both
    accept this shape (OpenAI wraps it in `function.parameters`, we
    adapt inside the provider).
    """

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ProviderResponse:
    """Normalized model response.

    Exactly one of `text` or `tool_calls` carries the payload:
      - `stop_reason == "tool_use"` → `tool_calls` populated, `text` None.
      - `stop_reason in {"end_turn", "stop", "max_tokens"}` → `text` populated.
    """

    text: str | None
    tool_calls: list[ToolCall]
    stop_reason: str


class Provider(Protocol):
    """OpenAI-style tool-calling chat."""

    model: str

    def chat(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        tool_choice: Literal["auto", "required", "none"] = "auto",
    ) -> ProviderResponse:
        ...


class StructuredOutputProvider(Protocol):
    """Fallback for models that can't reliably tool-call.

    The agent loop will construct a prompt like:
      "Call the `upsert_location` tool with these arguments. Return
      ONLY the JSON arguments matching this schema."
    and `generate_json` coerces the completion to match.
    """

    model: str

    def generate_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        ...
