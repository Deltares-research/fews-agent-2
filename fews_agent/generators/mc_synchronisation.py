"""McSynchronisation generator."""
from __future__ import annotations

from fews_agent.schema import McSynchronisation

from .base import render


def generate(model: McSynchronisation) -> str:
    return render("system/mc_synchronisation.xml.j2", model)
