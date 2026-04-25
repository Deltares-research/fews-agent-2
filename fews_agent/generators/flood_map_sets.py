"""FloodMapSets generator."""
from __future__ import annotations

from fews_agent.schema import FloodMapSets

from .base import render


def generate(model: FloodMapSets) -> str:
    return render("module/flood_map_sets.xml.j2", model)
