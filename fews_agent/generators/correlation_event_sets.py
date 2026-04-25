"""CorrelationEventSets generator."""
from __future__ import annotations

from fews_agent.schema import CorrelationEventSets

from .base import render


def generate(model: CorrelationEventSets) -> str:
    return render("region/correlation_event_sets.xml.j2", model)
