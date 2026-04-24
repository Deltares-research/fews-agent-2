"""ReportExport generator."""
from __future__ import annotations

from fews_agent.schema import ReportExport

from .base import render


def generate(model: ReportExport) -> str:
    return render("module/report_export.xml.j2", model)
