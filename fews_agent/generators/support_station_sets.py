"""SupportStationSets generator."""
from __future__ import annotations

from fews_agent.schema import SupportStationSets

from .base import render


def generate(model: SupportStationSets) -> str:
    return render("region/support_station_sets.xml.j2", model)
