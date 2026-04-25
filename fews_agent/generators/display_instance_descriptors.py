"""DisplayInstanceDescriptors generator."""
from __future__ import annotations

from fews_agent.schema import DisplayInstanceDescriptors

from .base import render


def generate(model: DisplayInstanceDescriptors) -> str:
    return render("static/display_instance_descriptors.xml.j2", model)
