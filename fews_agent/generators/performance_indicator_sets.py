"""PerformanceIndicatorSets generator."""
from __future__ import annotations

from fews_agent.schema import PerformanceIndicatorSets

from .base import render


def generate(model: PerformanceIndicatorSets) -> str:
    return render("region/performance_indicator_sets.xml.j2", model)
