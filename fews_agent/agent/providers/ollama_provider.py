"""Ollama backend.

Two code paths. The default uses ollama>=0.4's OpenAI-style tool-calling
— recent Qwen2.5, Llama 3.1/3.2, Mistral do this well. Smaller models
(phi3.5, tinyllama) return malformed JSON often enough to be unusable
in a tool loop, so those auto-route through a structured-output
fallback: one-shot prompted JSON generation where we parse the first
`{...}` we can find in the completion.

The fallback is lossy — no multi-turn tool correction, no chain of
calls — but it lets the user run cheap/fast local models for demo use.

Model choice:
  - Default `qwen2.5:7b-instruct` — strong tool calls, ~8GB RAM.
  - Set `FEWS_AGENT_MODEL=phi3.5` to use the fallback path explicitly.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from typing import Any, Literal

import ollama

from .base import (
    Message,
    ProviderResponse,
    StructuredResponse,
    ToolCall,
    ToolSpec,
)

_logger = logging.getLogger(__name__)

# Models known to be unreliable with tool calling; auto-route to
# structured-output fallback.
_FALLBACK_MODELS = {"phi3.5", "phi3", "phi3.5:latest", "tinyllama", "tinyllama:latest"}


def _ollama_usage(resp: Any) -> dict[str, int] | None:
    """Extract token counts from an ollama.chat response.

    Modern Ollama returns ``prompt_eval_count`` (input tokens) and
    ``eval_count`` (output tokens) at the top level of the dict. Older
    versions or some models may omit them — return None in that case.
    """
    try:
        prompt = resp.get("prompt_eval_count")
        completion = resp.get("eval_count")
    except AttributeError:
        return None
    if prompt is None and completion is None:
        return None
    return {
        "prompt_tokens": int(prompt or 0),
        "completion_tokens": int(completion or 0),
        "total_tokens": int((prompt or 0) + (completion or 0)),
    }


class OllamaProvider:
    """Ollama backend. Implements both Provider and StructuredOutputProvider."""

    def __init__(self, model: str = "qwen2.5:7b-instruct") -> None:
        self.model = model
        host = os.environ.get("OLLAMA_HOST")
        self._client = ollama.Client(host=host) if host else ollama.Client()
        self._use_fallback = self._should_fallback(model)
        if self._use_fallback:
            _logger.warning(
                "ollama model %r is a known tool-call-weak model; "
                "routing chat() through structured-output fallback",
                model,
            )

    @staticmethod
    def _should_fallback(model: str) -> bool:
        base = model.split("/", 1)[-1].lower()
        return base in _FALLBACK_MODELS or any(
            base.startswith(prefix) for prefix in ("phi3", "tinyllama")
        )

    # --- Provider -----------------------------------------------------

    def chat(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        tool_choice: Literal["auto", "required", "none"] = "auto",
    ) -> ProviderResponse:
        if self._use_fallback:
            return self._chat_via_fallback(system, messages, tools)

        payload_messages = self._to_ollama_messages(system, messages)
        payload_tools = [self._to_ollama_tool(t) for t in tools]

        try:
            resp = self._client.chat(
                model=self.model,
                messages=payload_messages,
                tools=payload_tools or None,
                options={"temperature": 0.2},
            )
        except Exception as exc:
            _logger.warning("ollama.chat failed (%s); switching to fallback", exc)
            self._use_fallback = True
            return self._chat_via_fallback(system, messages, tools)

        msg = resp.get("message") or {}
        raw_calls = msg.get("tool_calls") or []
        calls: list[ToolCall] = []
        for rc in raw_calls:
            fn = rc.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append(
                ToolCall(
                    id=rc.get("id") or f"call_{uuid.uuid4().hex[:12]}",
                    name=fn.get("name", ""),
                    arguments=args or {},
                )
            )

        return ProviderResponse(
            text=msg.get("content") or None,
            tool_calls=calls,
            stop_reason="tool_use" if calls else "end_turn",
            usage=_ollama_usage(resp),
        )

    # --- StructuredOutputProvider ------------------------------------

    def generate_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
    ) -> StructuredResponse:
        prompt = (
            f"{user}\n\nReturn ONLY a single JSON object matching this JSON schema "
            f"(no prose, no fences, no keys outside the schema):\n"
            f"{json.dumps(schema, indent=2)}"
        )
        resp = self._client.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            options={"temperature": 0.1},
        )
        content = (resp.get("message") or {}).get("content", "")
        data = self._extract_json(content, required=False)
        return StructuredResponse(data=data, usage=_ollama_usage(resp))

    # --- helpers -----------------------------------------------------

    def _chat_via_fallback(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> ProviderResponse:
        """Single-shot: ask the model to either produce plain text
        OR one tool call as JSON. Return whichever we can parse.

        This is the phi3.5 happy path. It can't do multi-call loops but
        completes one action per turn, which is enough for the demo.
        """
        tool_docs = "\n".join(
            f"- {t.name}({json.dumps(t.input_schema.get('properties', {}))}) — {t.description}"
            for t in tools
        )
        latest_user = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )
        instruction = (
            "Available tools:\n"
            f"{tool_docs}\n\n"
            "Either answer the user directly, or respond with a JSON object "
            '{"tool": "<name>", "arguments": { ... }} to call a tool. '
            "No other format is accepted.\n\n"
            f"User: {latest_user}"
        )
        resp = self._client.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": instruction},
            ],
            options={"temperature": 0.1},
        )
        content = (resp.get("message") or {}).get("content", "")
        obj = self._extract_json(content, required=False)
        usage = _ollama_usage(resp)
        if isinstance(obj, dict) and "tool" in obj:
            return ProviderResponse(
                text=None,
                tool_calls=[
                    ToolCall(
                        id=f"call_{uuid.uuid4().hex[:12]}",
                        name=str(obj.get("tool", "")),
                        arguments=dict(obj.get("arguments") or {}),
                    )
                ],
                stop_reason="tool_use",
                usage=usage,
            )
        return ProviderResponse(
            text=content, tool_calls=[], stop_reason="end_turn", usage=usage
        )

    @staticmethod
    def _to_ollama_messages(system: str, messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            if m.role == "tool":
                # Ollama's tool-role message: { role: "tool", content: str, tool_name: str }
                out.append(
                    {"role": "tool", "content": m.content, "tool_call_id": m.tool_call_id or ""}
                )
                continue
            entry: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": c.arguments},
                    }
                    for c in m.tool_calls
                ]
            out.append(entry)
        return out

    @staticmethod
    def _to_ollama_tool(tool: ToolSpec) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }

    @staticmethod
    def _extract_json(text: str, required: bool = True) -> dict[str, Any]:  # noqa: D401
        """Find the first balanced `{...}` block and parse it.

        Small models often wrap JSON in ```json fences or prefix it with
        prose; this scavenges through both.
        """
        # Strip code fences
        cleaned = re.sub(r"```(?:json)?\s*", "", text)
        cleaned = cleaned.replace("```", "").strip()
        # Direct parse first
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        # Find a balanced object
        depth = 0
        start = -1
        for i, ch in enumerate(cleaned):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start != -1:
                    chunk = cleaned[start : i + 1]
                    try:
                        parsed = json.loads(chunk)
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        continue
        if required:
            raise ValueError(f"no JSON object found in model output: {text!r}")
        return {}
