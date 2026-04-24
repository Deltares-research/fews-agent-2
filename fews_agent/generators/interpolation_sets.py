"""InterpolationSets generator."""
from __future__ import annotations

from fews_agent.schema import InterpolationSets

from .base import render


def generate(model: InterpolationSets) -> str:
    return render("region/interpolation_sets.xml.j2", model)
