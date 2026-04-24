"""CalibrationSet generator."""
from __future__ import annotations

from fews_agent.schema import CalibrationSet

from .base import render


def generate(model: CalibrationSet) -> str:
    return render("module/calibration.xml.j2", model)
