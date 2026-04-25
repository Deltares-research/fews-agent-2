"""WaterCoachScript generator."""
from __future__ import annotations

from .base import render
from ..schema.water_coach_script import WaterCoachScript


def generate(model: WaterCoachScript) -> str:
    return render("system/water_coach_script.xml.j2", model)
