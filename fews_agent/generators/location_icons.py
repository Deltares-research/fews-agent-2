"""LocationIcons generator."""
from __future__ import annotations

from fews_agent.schema import LocationIcons

from .base import render


def generate(model: LocationIcons) -> str:
    return render("location_icons.xml.j2", model)
