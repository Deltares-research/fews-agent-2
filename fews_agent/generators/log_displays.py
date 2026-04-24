"""LogDisplays generator."""
from __future__ import annotations

from fews_agent.schema import LogDisplays

from .base import render


def generate(model: LogDisplays) -> str:
    return render("display/log_displays.xml.j2", model)
