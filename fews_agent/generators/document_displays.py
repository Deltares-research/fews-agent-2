"""DocumentDisplays generator."""
from __future__ import annotations

from fews_agent.schema import DocumentDisplays

from .base import render


def generate(model: DocumentDisplays) -> str:
    return render("display/document_displays.xml.j2", model)
