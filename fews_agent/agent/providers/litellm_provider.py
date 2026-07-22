"""LiteLLM backend — one wrapper, many backends.

LiteLLM normalises every provider it supports into an OpenAI-shaped
``completion()`` call, so a single provider class can route to HF
Inference Providers, Together, Replicate, Anthropic, OpenAI, etc.
The backend is selected by the model string:

  - ``huggingface/Qwen/Qwen2.5-7B-Instruct``      — HF Inference API
  - ``huggingface/together/meta-llama/Llama-3.1-8B-Instruct``
                                                   — HF routed via Together
  - ``together_ai/meta-llama/Llama-3.1-8B-Instruct``
  - ``anthropic/claude-haiku-4-5``
  - ``openai/gpt-4o-mini``
  - ``ollama/qwen2.5:7b-instruct``                — local Ollama

API keys are picked up from env vars LiteLLM already documents
(``HF_TOKEN``, ``TOGETHER_API_KEY``, ``ANTHROPIC_API_KEY`` …) — this
provider doesn't override that. The user sets:

  FEWS_AGENT_PROVIDER=litellm
  FEWS_AGENT_MODEL=huggingface/Qwen/Qwen2.5-7B-Instruct
  HF_TOKEN=hf_...

Tool calling: LiteLLM passes OpenAI-style ``tools`` / ``tool_choice``
through to whichever backend supports it. Models that don't tool-call
return an empty ``tool_calls`` list — generate_json() is the fallback
path for those.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Literal

import litellm

from .base import (
    Message,
    ProviderResponse,
    StructuredResponse,
    ToolCall,
    ToolSpec,
)

_logger = logging.getLogger(__name__)

# Drop params a given backend doesn't accept instead of erroring. Without this,
# a fixed ``temperature=0.2`` hard-fails on models that only allow the default
# (e.g. Azure gpt-5.x: "gpt-5 models don't support temperature=0.2") — which
# silently sank EVERY LiteLLM call (parse_turn, compose_reply, the filter
# drafter) to its deterministic fallback. LiteLLM's documented switch for this.
litellm.drop_params = True


class LiteLLMProvider:
    """LiteLLM-routed backend. Implements Provider and StructuredOutputProvider."""

    def __init__(self, model: str = "huggingface/Qwen/Qwen2.5-7B-Instruct") -> None:
        self.model = model

    # --- Provider -----------------------------------------------------

    def chat(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        tool_choice: Literal["auto", "required", "none"] = "auto",
    ) -> ProviderResponse:
        payload_messages = self._to_openai_messages(system, messages)
        payload_tools = [self._to_openai_tool(t) for t in tools] or None

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": payload_messages,
            "temperature": 0.2,
        }
        if payload_tools:
            kwargs["tools"] = payload_tools
            kwargs["tool_choice"] = tool_choice

        resp = litellm.completion(**kwargs)
        choice = resp.choices[0]
        msg = choice.message

        calls: list[ToolCall] = []
        for rc in (getattr(msg, "tool_calls", None) or []):
            fn = getattr(rc, "function", None)
            args = getattr(fn, "arguments", None) if fn is not None else None
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append(
                ToolCall(
                    id=getattr(rc, "id", None) or f"call_{uuid.uuid4().hex[:12]}",
                    name=getattr(fn, "name", "") if fn is not None else "",
                    arguments=args or {},
                )
            )

        return ProviderResponse(
            text=getattr(msg, "content", None) or None,
            tool_calls=calls,
            stop_reason="tool_use" if calls else (choice.finish_reason or "end_turn"),
            usage=self._usage(resp),
        )

    # --- StructuredOutputProvider ------------------------------------

    def generate_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        on_delta=None,
    ) -> StructuredResponse:
        """Structured call. With ``on_delta``, the response streams and the
        callback receives the ``"reply"`` field's text as it arrives (the
        full JSON is still parsed normally at the end). Any streaming
        failure falls back to the plain call — streaming is a UX nicety,
        never a correctness dependency."""
        prompt = (
            f"{user}\n\nReturn ONLY a single JSON object matching this JSON schema "
            f"(no prose, no fences, no keys outside the schema):\n"
            f"{json.dumps(schema, indent=2)}"
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        if on_delta is not None:
            try:
                return self._generate_json_streaming(messages, on_delta)
            except Exception:  # noqa: BLE001 — fall back to non-streaming
                pass
        resp = litellm.completion(
            model=self.model, messages=messages, temperature=0.1,
        )
        content = resp.choices[0].message.content or ""
        data = self._extract_json(content)
        return StructuredResponse(data=data, usage=self._usage(resp))

    def _generate_json_streaming(self, messages, on_delta) -> StructuredResponse:
        from fews_agent.agent.reply_stream import ReplyStreamExtractor

        stream = litellm.completion(
            model=self.model, messages=messages, temperature=0.1,
            stream=True, stream_options={"include_usage": True},
        )
        extractor = ReplyStreamExtractor()
        parts: list[str] = []
        usage = None
        for chunk in stream:
            u = self._usage(chunk)
            if u:
                usage = u
            choices = getattr(chunk, "choices", None) or []
            delta = (getattr(choices[0].delta, "content", None)
                     if choices else None)
            if delta:
                parts.append(delta)
                fresh = extractor.feed(delta)
                if fresh:
                    try:
                        on_delta(fresh)
                    except Exception:  # noqa: BLE001 — UI must not kill the call
                        pass
        content = "".join(parts)
        data = self._extract_json(content)
        return StructuredResponse(data=data, usage=usage)

    # --- helpers -----------------------------------------------------

    @staticmethod
    def _usage(resp: Any) -> dict[str, int] | None:
        u = getattr(resp, "usage", None)
        if u is None:
            return None
        prompt = getattr(u, "prompt_tokens", 0) or 0
        completion = getattr(u, "completion_tokens", 0) or 0
        if not prompt and not completion:
            return None
        return {
            "prompt_tokens": int(prompt),
            "completion_tokens": int(completion),
            "total_tokens": int(prompt + completion),
        }

    @staticmethod
    def _to_openai_messages(
        system: str, messages: list[Message],
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            if m.role == "tool":
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": m.tool_call_id or "",
                        "content": m.content,
                    }
                )
                continue
            entry: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.name,
                            "arguments": json.dumps(c.arguments),
                        },
                    }
                    for c in m.tool_calls
                ]
            out.append(entry)
        return out

    @staticmethod
    def _to_openai_tool(tool: ToolSpec) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        cleaned = re.sub(r"```(?:json)?\s*", "", text)
        cleaned = cleaned.replace("```", "").strip()
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
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
        return {}
