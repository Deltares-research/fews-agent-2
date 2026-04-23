"""TimeSeriesTableDisplay generator."""
from __future__ import annotations

from fews_agent.schema import TimeSeriesTableDisplay

from .base import render


def generate(model: TimeSeriesTableDisplay) -> str:
    return render("display/time_series_table_display.xml.j2", model)
