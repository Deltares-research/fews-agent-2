"""Locations generator."""
from __future__ import annotations

from fews_agent.schema import Locations

from .base import render


def generate(model: Locations) -> str:
    return render("locations.xml.j2", model)
