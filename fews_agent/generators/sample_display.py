"""SampleDisplay generator."""
from __future__ import annotations

from fews_agent.schema import SampleDisplay

from .base import render


def generate(model: SampleDisplay) -> str:
    return render("display/sample_display.xml.j2", model)
