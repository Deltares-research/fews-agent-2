"""RunInfoPanel generator."""
from __future__ import annotations

from fews_agent.schema import RunInfoPanel

from .base import render


def generate(model: RunInfoPanel) -> str:
    return render("root/run_info_panel.xml.j2", model)
