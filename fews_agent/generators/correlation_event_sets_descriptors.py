"""CorrelationEventSetsDescriptors generator."""
from __future__ import annotations

from fews_agent.schema import CorrelationEventSetsDescriptors

from .base import render


def generate(model: CorrelationEventSetsDescriptors) -> str:
    return render("region/correlation_event_sets_descriptors.xml.j2", model)
