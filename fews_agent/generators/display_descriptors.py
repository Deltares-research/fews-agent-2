"""DisplayDescriptors generator."""
from __future__ import annotations

from fews_agent.schema import DisplayDescriptors

from .base import render


def generate(model: DisplayDescriptors) -> str:
    return render("static/display_descriptors.xml.j2", model)
