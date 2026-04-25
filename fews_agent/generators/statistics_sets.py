"""StatisticsSets generator."""
from __future__ import annotations

from fews_agent.schema import StatisticsSets

from .base import render


def generate(model: StatisticsSets) -> str:
    return render("module/statistics_sets.xml.j2", model)
