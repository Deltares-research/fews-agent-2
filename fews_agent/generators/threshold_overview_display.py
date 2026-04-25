"""ThresholdOverviewDisplay generator."""
from __future__ import annotations

from fews_agent.schema import ThresholdOverviewDisplay

from .base import render


def generate(model: ThresholdOverviewDisplay) -> str:
    return render("display/threshold_overview_display.xml.j2", model)
