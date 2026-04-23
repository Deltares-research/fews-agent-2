"""DoubleMassDisplay generator."""
from __future__ import annotations

from fews_agent.schema import DoubleMassDisplay

from .base import render


def generate(model: DoubleMassDisplay) -> str:
    return render("display/double_mass_display.xml.j2", model)
