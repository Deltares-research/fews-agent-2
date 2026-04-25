"""TimeSeriesDisplayConfig generator."""
from __future__ import annotations

from fews_agent.schema import TimeSeriesDisplay

from .base import render


def generate(model: TimeSeriesDisplay) -> str:
    return render("system/time_series_display_config.xml.j2", model)
