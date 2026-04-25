"""FloodPeriodsModule generator."""
from __future__ import annotations

from fews_agent.schema import FloodPeriodsModule

from .base import render


def generate(model: FloodPeriodsModule) -> str:
    return render("module/flood_periods_module.xml.j2", model)
