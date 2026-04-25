"""LookupDisplay generator."""
from __future__ import annotations

from fews_agent.schema import LookupDisplay

from .base import render


def generate(model: LookupDisplay) -> str:
    return render("display/lookup_display.xml.j2", model)
