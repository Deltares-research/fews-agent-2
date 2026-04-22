"""ForecastLengthEstimator generator (SetForecastLength template)."""
from __future__ import annotations

from fews_agent.schema import ForecastLengthEstimator

from .base import render


def generate(model: ForecastLengthEstimator) -> str:
    return render("forecast_length_estimator.xml.j2", model)
