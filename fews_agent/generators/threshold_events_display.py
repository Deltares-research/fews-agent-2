"""ThresholdEventsDisplay generator."""
from __future__ import annotations

from fews_agent.schema import ThresholdEventsDisplay

from .base import render


def generate(model: ThresholdEventsDisplay) -> str:
    return render("display/threshold_events_display.xml.j2", model)
