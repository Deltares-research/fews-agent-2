"""GribTimeSeriesReader generator."""
from __future__ import annotations

from fews_agent.schema import GribTimeSeriesReader

from .base import render


def generate(model: GribTimeSeriesReader) -> str:
    return render("module/grib_time_series_reader.xml.j2", model)
