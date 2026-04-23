"""TrendDisplay generator."""
from __future__ import annotations

from fews_agent.schema import TrendDisplay

from .base import render


def generate(model: TrendDisplay) -> str:
    return render("display/trend_display.xml.j2", model)
