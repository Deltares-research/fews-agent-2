"""ValueAttributeMaps generator."""
from __future__ import annotations

from fews_agent.schema import ValueAttributeMaps

from .base import render


def generate(model: ValueAttributeMaps) -> str:
    return render("region/value_attribute_maps.xml.j2", model)
