"""HistoricalEvents generator."""
from __future__ import annotations

from fews_agent.schema import HistoricalEvents

from .base import render


def generate(model: HistoricalEvents) -> str:
    return render("region/historical_events.xml.j2", model)
