"""OpenDACalibrationDisplay generator."""
from __future__ import annotations

from fews_agent.schema import OpenDACalibrationDisplay

from .base import render


def generate(model: OpenDACalibrationDisplay) -> str:
    return render("display/openda_calibration_display.xml.j2", model)
