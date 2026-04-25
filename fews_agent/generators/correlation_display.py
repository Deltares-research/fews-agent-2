"""CorrelationDisplay generator."""
from __future__ import annotations

from fews_agent.schema import CorrelationDisplay

from .base import render


def generate(model: CorrelationDisplay) -> str:
    return render("display/correlation_display.xml.j2", model)
