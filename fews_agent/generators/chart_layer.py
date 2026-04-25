"""ChartLayer generator."""
from __future__ import annotations

from .base import render
from ..schema.chart_layer import ChartLayer


def generate(model: ChartLayer) -> str:
    return render("display/chart_layer.xml.j2", model)
