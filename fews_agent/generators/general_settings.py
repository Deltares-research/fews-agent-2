"""GeneralSettings generator."""
from __future__ import annotations

from fews_agent.schema import GeneralSettings

from .base import render


def generate(model: GeneralSettings) -> str:
    return render("root/general_settings.xml.j2", model)
