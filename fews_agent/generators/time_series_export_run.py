"""TimeSeriesExportRun generator."""
from __future__ import annotations

from .base import render
from ..schema.time_series_export_run import TimeSeriesExportRun


def generate(model: TimeSeriesExportRun) -> str:
    return render("module/time_series_export_run.xml.j2", model)
