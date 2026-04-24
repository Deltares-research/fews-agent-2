"""ObjectiveAnalyzerDisplay generator."""
from __future__ import annotations

from fews_agent.schema import ObjectiveAnalyzerDisplay

from .base import render


def generate(model: ObjectiveAnalyzerDisplay) -> str:
    return render("display/objective_analyzer_display.xml.j2", model)
