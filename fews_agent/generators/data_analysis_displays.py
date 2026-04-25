"""DataAnalysisDisplays generator."""
from __future__ import annotations

from fews_agent.schema import DataAnalysisDisplays

from .base import render


def generate(model: DataAnalysisDisplays) -> str:
    return render("display/data_analysis_displays.xml.j2", model)
