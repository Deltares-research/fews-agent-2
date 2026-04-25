"""WapdaTimeSeriesReader generator."""
from __future__ import annotations

from fews_agent.schema import WapdaTimeSeriesReader

from .base import render


def generate(model: WapdaTimeSeriesReader) -> str:
    return render("module/wapda_timeseries_reader.xml.j2", model)
