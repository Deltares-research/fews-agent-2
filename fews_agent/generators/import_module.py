"""ImportModule generator — shared across all Import/**/*.xml files."""
from __future__ import annotations

from fews_agent.schema import TimeSeriesImportRun

from .base import render


def generate(model: TimeSeriesImportRun) -> str:
    return render("import_module.xml.j2", model)
