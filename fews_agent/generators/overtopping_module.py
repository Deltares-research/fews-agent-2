"""OvertoppingModule generator."""
from __future__ import annotations

from fews_agent.schema import OvertoppingModule

from .base import render


def generate(model: OvertoppingModule) -> str:
    return render("module/overtopping_module.xml.j2", model)
