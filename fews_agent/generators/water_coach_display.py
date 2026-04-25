"""WaterCoachDisplay generator."""
from __future__ import annotations

from fews_agent.schema import WaterCoachDisplay

from .base import render


def generate(model: WaterCoachDisplay) -> str:
    return render("display/water_coach_display.xml.j2", model)
