"""Azure OpenAI backend.

Used when the agent is deployed somewhere that can't (or shouldn't)
host Ollama itself — typically Azure Container Apps reaching an
Azure OpenAI deployment. The deployed container becomes stateless and
small; Azure handles the model.

Mirrors ``OllamaProvider``'s interface (Provider + StructuredOutputProvider)
so callers don't care which backend they're talking to.

Environment variables (read at construction time, no fallback chain
beyond what's listed — fail loudly if they're missing):

  AZURE_OPENAI_ENDPOINT     https://<resource>.openai.azure.com
  AZURE_OPENAI_API_KEY      the resource key
  AZURE_OPENAI_API_VERSION  defaults to "2024-10-21"
  AZURE_OPENAI_DEPLOYMENT   deployment name (Azure's "model" field).
                            Overrides the ``model`` ctor arg when set —
                            Azure deployments are usually named per
                            environment (e.g. "gpt-4o-mini-prod"),
                            not after the underlying model id.

Why a separate provider rather than reusing OpenAIProvider: Azure's
client wants ``azure_endpoint`` + ``api_version`` and uses deployment
names as the ``model`` parameter. The request/response payloads are
otherwise the OpenAI chat-completions shape verbatim.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from typing import Any, Literal

from openai import AzureOpenAI

from .base import (
    Message,
    ProviderResponse,
    StructuredResponse,
    ToolCall,
    ToolSpec,
)

_logger = logging.getLogger(__name__)

_DEFAULT_API_VERSION = "2024-10-21"


def _openai_usage(resp: Any) -> dict[str, int] | None:
    """Extract token counts from an OpenAI ChatCompletion response."""
    usage = getattr(resp, "usage", None)
    if usage is None:
        return None
    prompt = getattr(usage, "prompt_tokens", 0) or 0
    completion = getattr(usage, "completion_tokens", 0) or 0
    return {
        "prompt_tokens": int(prompt),
        "completion_tokens": int(completion),
        "total_tokens": int(prompt + completion),
    }


class AzureOpenAIProvider:
    """Azure OpenAI Chat Completions backend."""

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        api_version = os.environ.get("AZURE_OPENAI_API_VERSION") or _DEFAULT_API_VERSION
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")

        if not endpoint:
            raise RuntimeError(
                "AZURE_OPENAI_ENDPOINT is not set. "
                "Set it to https://<resource>.openai.azure.com in your environment."
            )
        if not api_key:
            raise RuntimeError(
                "AZURE_OPENAI_API_KEY is not set. "
                "Add the resource key to your environment."
            )

        # Deployment name wins over the model arg, since Azure treats
        # the ``model`` request field as a deployment id, not a model id.
        self.model = deployment or model
        self._client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )

    # --- Provider -----------------------------------------------------

    def chat(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        tool_choice: Literal["auto", "required", "none"] = "auto",
    ) -> ProviderResponse:
        payload_messages = self._to_openai_messages(system, messages)
        payload_tools = [self._to_openai_tool(t) for t in tools]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": payload_messages,
            "temperature": 0.2,
        }
        if payload_tools:
            kwargs["tools"] = payload_tools
            kwargs["tool_choice"] = tool_choice

        resp = self._client.chat.completions.create(**kwargs)

        msg = resp.choices[0].message
        calls: list[ToolCall] = []
        for rc in (msg.tool_calls or []):
            fn = rc.function
            args = fn.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append(
                ToolCall(
                    id=rc.id or f"call_{uuid.uuid4().hex[:12]}",
                    name=fn.name or "",
                    arguments=dict(args or {}),
                )
            )

        return ProviderResponse(
            text=(msg.content or None) if not calls else (msg.content or None),
            tool_calls=calls,
            stop_reason="tool_use" if calls else (resp.choices[0].finish_reason or "end_turn"),
            usage=_openai_usage(resp),
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
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        content = resp.choices[0].message.content or ""
        data = self._extract_json(content, required=False)
        return StructuredResponse(data=data, usage=_openai_usage(resp))

    # --- helpers -----------------------------------------------------

    @staticmethod
    def _to_openai_messages(system: str, messages: list[Message]) -> list[dict[str, Any]]:
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
    def _extract_json(text: str, required: bool = True) -> dict[str, Any]:
        """Find the first balanced ``{...}`` block and parse it.

        With ``response_format=json_object`` the model usually returns
        clean JSON, but we still scavenge for a balanced object as a
        safety net.
        """
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
        if required:
            raise ValueError(f"no JSON object found in model output: {text!r}")
        return {}
