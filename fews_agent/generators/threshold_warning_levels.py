"""ThresholdWarningLevels generator."""
from __future__ import annotations

from fews_agent.schema import ThresholdWarningLevels

from .base import render


def generate(model: ThresholdWarningLevels) -> str:
    return render("region/threshold_warning_levels.xml.j2", model)
