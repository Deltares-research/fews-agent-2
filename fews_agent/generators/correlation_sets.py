"""CorrelationSets generator."""
from __future__ import annotations

from fews_agent.schema import CorrelationSets

from .base import render


def generate(model: CorrelationSets) -> str:
    return render("region/correlation_sets.xml.j2", model)
