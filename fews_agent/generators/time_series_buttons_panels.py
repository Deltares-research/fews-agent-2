"""TimeSeriesButtonsPanels generator."""
from __future__ import annotations

from fews_agent.schema import TimeSeriesButtonsPanels

from .base import render


def generate(model: TimeSeriesButtonsPanels) -> str:
    return render("display/time_series_buttons_panels.xml.j2", model)
