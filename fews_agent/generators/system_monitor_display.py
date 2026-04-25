"""SystemMonitorDisplay generator."""
from __future__ import annotations

from fews_agent.schema import SystemMonitorDisplay

from .base import render


def generate(model: SystemMonitorDisplay) -> str:
    return render("display/system_monitor_display.xml.j2", model)
