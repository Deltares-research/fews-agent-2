"""Polygons generator."""
from __future__ import annotations

from fews_agent.schema import Polygons

from .base import render


def generate(model: Polygons) -> str:
    return render("region/polygons.xml.j2", model)
