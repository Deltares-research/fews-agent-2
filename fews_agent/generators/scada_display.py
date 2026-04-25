"""ScadaDisplay generator."""
from __future__ import annotations

from .base import render
from ..schema.scada_display import ScadaDisplay


def generate(model: ScadaDisplay) -> str:
    return render("display/scada_display.xml.j2", model)
