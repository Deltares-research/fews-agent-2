"""IdMapDescriptors generator."""
from __future__ import annotations

from fews_agent.schema import IdMapDescriptors

from .base import render


def generate(model: IdMapDescriptors) -> str:
    return render("static/id_map_descriptors.xml.j2", model)
