"""WaterCoachDictionary generator."""
from __future__ import annotations

from fews_agent.schema import WaterCoachDictionary

from .base import render


def generate(model: WaterCoachDictionary) -> str:
    return render("display/water_coach_dictionary.xml.j2", model)
