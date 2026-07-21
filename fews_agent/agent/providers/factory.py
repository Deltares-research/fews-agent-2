"""Provider factory — resolve (name, model) to a Provider instance.

Wiring is driven by environment variables so callers (TUI, web app,
runners) can change provider without code edits:

    FEWS_AGENT_PROVIDER = ollama | azure | anthropic | litellm | hf
                         | openai | gemini
    FEWS_AGENT_MODEL    = provider-specific model id (or the Azure
                          deployment name when provider=azure)

Defaults: ollama + qwen2.5:7b-instruct. ``azure`` is the cloud path
used by the deployed web app — see ``azure_openai_provider.py`` for
the AZURE_OPENAI_* env vars it expects.

``litellm`` routes through LiteLLM, which picks the real backend from
the model string prefix — e.g. ``huggingface/...``, ``together_ai/...``,
``anthropic/...``. ``hf`` is shorthand for litellm with the model
forced to ``huggingface/<FEWS_AGENT_MODEL>`` (HF Inference Providers).

OpenAI and Gemini are not implemented as standalone providers — set
``FEWS_AGENT_PROVIDER=litellm`` with model ``openai/...`` or
``gemini/...`` instead.
"""
from __future__ import annotations

import os

from .base import Provider


_DEFAULT_MODELS = {
    "ollama": "qwen2.5:7b-instruct",
    "azure": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5",
    "litellm": "huggingface/Qwen/Qwen2.5-7B-Instruct",
    "hf": "Qwen/Qwen2.5-7B-Instruct",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.5-flash",
}

# Aliases — let the env var be written naturally
# (FEWS_AGENT_PROVIDER=AZURE works, as does =azure_openai).
_PROVIDER_ALIASES = {
    "azure_openai": "azure",
    "azure-openai": "azure",
    "azureopenai": "azure",
    "huggingface": "hf",
    "hugging_face": "hf",
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
    if name == "litellm":
        from .litellm_provider import LiteLLMProvider

        return LiteLLMProvider(model=model)
    if name == "hf":
        from .litellm_provider import LiteLLMProvider

        # 'hf' is a shorthand: prepend the LiteLLM HuggingFace prefix
        # unless the user already wrote a fully-qualified model id.
        if not model.startswith("huggingface/"):
            model = f"huggingface/{model}"
        return LiteLLMProvider(model=model)
    if name in {"openai", "gemini"}:
        raise NotImplementedError(
            f"Provider {name!r} not wired as a standalone backend. "
            f"Use FEWS_AGENT_PROVIDER=litellm with model "
            f"'{name}/<model-id>' instead."
        )
    raise ValueError(f"unknown provider: {name!r}")


def default_model(name: str) -> str:
    return _DEFAULT_MODELS.get(name.lower(), "")


def get_provider_or_ollama(model: str) -> Provider:
    """Resolve provider for code paths that still default to Ollama.

    If ``FEWS_AGENT_PROVIDER`` is set, dispatch through the factory.
    Otherwise return ``OllamaProvider(model=model)`` so the CLI
    ``--model`` flag (which only makes sense for Ollama) keeps working
    unchanged. Used by chat_step.py, the filter drafter, and the
    intent helpers — anywhere a provider parameter defaults to
    Ollama for backward compat.
    """
    if os.environ.get("FEWS_AGENT_PROVIDER"):
        return get_provider()
    from .ollama_provider import OllamaProvider
    return OllamaProvider(model=model)
