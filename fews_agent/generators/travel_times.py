"""TravelTimes generator."""
from __future__ import annotations

from fews_agent.schema import TravelTimes

from .base import render


def generate(model: TravelTimes) -> str:
    return render("region/travel_times.xml.j2", model)
