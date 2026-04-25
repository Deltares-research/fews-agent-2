"""WebService generator."""
from __future__ import annotations

from fews_agent.schema import WebService

from .base import render


def generate(model: WebService) -> str:
    return render("module/web_service.xml.j2", model)
