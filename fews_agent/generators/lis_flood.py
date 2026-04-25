"""LisFlood generator."""
from __future__ import annotations

from fews_agent.schema import LisFlood

from .base import render


def generate(model: LisFlood) -> str:
    return render("module/lis_flood.xml.j2", model)
