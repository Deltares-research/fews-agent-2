"""PrtfDisplay generator."""
from __future__ import annotations

from fews_agent.schema import PRTFDisplay

from .base import render


def generate(model: PRTFDisplay) -> str:
    return render("display/prtf_display.xml.j2", model)
