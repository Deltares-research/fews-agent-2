"""ManualForecastDisplay generator."""
from __future__ import annotations

from fews_agent.schema import ManualForecastDisplay

from .base import render


def generate(model: ManualForecastDisplay) -> str:
    return render("display/manual_forecast_display.xml.j2", model)
