"""TravelTimesDescriptors generator."""
from __future__ import annotations

from fews_agent.schema import TravelTimesDescriptors

from .base import render


def generate(model: TravelTimesDescriptors) -> str:
    return render("region/travel_times_descriptors.xml.j2", model)
