"""DynamicReportDisplays generator."""
from __future__ import annotations

from fews_agent.schema import DynamicReportDisplays

from .base import render


def generate(model: DynamicReportDisplays) -> str:
    return render("display/dynamic_report_displays.xml.j2", model)
