"""ForecastMixer generator."""
from __future__ import annotations

from fews_agent.schema import ForecastMixer

from .base import render


def generate(model: ForecastMixer) -> str:
    return render("module/forecast_mixer.xml.j2", model)
