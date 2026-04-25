"""ForecastManagement generator."""
from __future__ import annotations

from fews_agent.schema import ForecastManagement

from .base import render


def generate(model: ForecastManagement) -> str:
    return render("display/forecast_management.xml.j2", model)
