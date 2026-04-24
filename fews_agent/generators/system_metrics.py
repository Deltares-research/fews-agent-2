"""SystemMetrics generator."""
from __future__ import annotations

from fews_agent.schema import SystemMetrics

from .base import render


def generate(model: SystemMetrics) -> str:
    return render("system/system_metrics.xml.j2", model)
