"""Provider factory — resolve (name, model) to a Provider instance.

Wiring is driven by environment variables so callers (TUI, web app,
runners) can change provider without code edits:

    FEWS_AGENT_PROVIDER = ollama | azure | anthropic | openai | gemini
    FEWS_AGENT_MODEL    = provider-specific model id (or Azure
                          deployment name when provider=azure; can also
                          be set via AZURE_OPENAI_DEPLOYMENT)

Defaults: ollama + qwen2.5:7b-instruct. ``azure`` is the cloud path
used by the deployed web app — see ``azure_openai_provider.py`` for
the AZURE_OPENAI_* env vars it expects.

OpenAI and Gemini are not implemented — they raise NotImplementedError
with a pointer to the right file to add.
"""
from __future__ import annotations

import os

from .base import Provider


_DEFAULT_MODELS = {
    "ollama": "qwen2.5:7b-instruct",
    "azure": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.5-flash",
}

# Aliases — let the env var be written naturally
# (FEWS_AGENT_PROVIDER=AZURE works, as does =azure_openai).
_PROVIDER_ALIASES = {
    "azure_openai": "azure",
    "azure-openai": "azure",
    "azureopenai": "azure",
}


def get_provider(name: str | None = None, model: str | None = None) -> Provider:
    name = (name or os.environ.get("FEWS_AGENT_PROVIDER") or "ollama").lower().strip()
    name = _PROVIDER_ALIASES.get(name, name)
    model = (model or os.environ.get("FEWS_AGENT_MODEL") or _DEFAULT_MODELS.get(name, "")).strip()

    if name == "ollama":
        from .ollama_provider import OllamaProvider

        return OllamaProvider(model=model)
    if name == "azure":
        from .azure_openai_provider import AzureOpenAIProvider

        return AzureOpenAIProvider(model=model)
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
