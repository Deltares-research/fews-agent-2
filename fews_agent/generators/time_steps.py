"""TimeSteps generator."""
from __future__ import annotations

from fews_agent.schema import TimeSteps

from .base import render


def generate(model: TimeSteps) -> str:
    return render("time_steps.xml.j2", model)
