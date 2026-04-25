"""ForecastProductInfoDisplay generator."""
from __future__ import annotations

from fews_agent.schema import ForecastProductInfoDisplay

from .base import render


def generate(model: ForecastProductInfoDisplay) -> str:
    return render("display/forecast_product_info_display.xml.j2", model)
