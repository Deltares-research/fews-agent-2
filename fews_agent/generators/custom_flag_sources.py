"""CustomFlagSources generator."""
from __future__ import annotations

from fews_agent.schema import CustomFlagSources

from .base import render


def generate(model: CustomFlagSources) -> str:
    return render("region/custom_flag_sources.xml.j2", model)
