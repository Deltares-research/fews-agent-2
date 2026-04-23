"""ClobHistoricalEvent generator."""
from __future__ import annotations

from fews_agent.schema import ClobHistoricalEvent

from .base import render


def generate(model: ClobHistoricalEvent) -> str:
    return render("region/clob_historical_event.xml.j2", model)
