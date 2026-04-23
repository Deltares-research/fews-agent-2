"""Provider factory — resolve (name, model) to a Provider instance.

Wiring is driven by environment variables so the TUI can change
provider without code edits:

    FEWS_AGENT_PROVIDER = ollama | anthropic | openai | gemini
    FEWS_AGENT_MODEL    = provider-specific model id

Defaults: ollama + qwen2.5:7b-instruct. OpenAI and Gemini are not
implemented in slice 1 — they raise NotImplementedError with a
pointer to the right file to add.
"""
from __future__ import annotations

import os

from .base import Provider


_DEFAULT_MODELS = {
    "ollama": "qwen2.5:7b-instruct",
    "anthropic": "claude-haiku-4-5",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.5-flash",
}


def get_provider(name: str | None = None, model: str | None = None) -> Provider:
    name = (name or os.environ.get("FEWS_AGENT_PROVIDER") or "ollama").lower().strip()
    model = (model or os.environ.get("FEWS_AGENT_MODEL") or _DEFAULT_MODELS.get(name, "")).strip()

    if name == "ollama":
        from .ollama_provider import OllamaProvider

        return OllamaProvider(model=model)
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(model=model)
    if name in {"openai", "gemini"}:
        raise NotImplementedError(
            f"Provider {name!r} not wired in slice 1. "
            f"Add fews_agent/agent/providers/{name}_provider.py mirroring anthropic_provider.py."
        )
    raise ValueError(f"unknown provider: {name!r}")


def default_model(name: str) -> str:
    return _DEFAULT_MODELS.get(name.lower(), "")
