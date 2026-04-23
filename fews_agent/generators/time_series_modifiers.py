"""TimeSeriesModifiers generator."""
from __future__ import annotations

from fews_agent.schema import TimeSeriesModifiers

from .base import render


def generate(model: TimeSeriesModifiers) -> str:
    return render("region/time_series_modifiers.xml.j2", model)
