"""WebOCComponentSettings generator."""
from __future__ import annotations

from fews_agent.schema import WebOCComponentSettings

from .base import render


def generate(model: WebOCComponentSettings) -> str:
    return render("system/web_oc_component_settings.xml.j2", model)
