"""EnvironmentAgencyTimeUnits generator."""
from __future__ import annotations

from fews_agent.schema import EnvironmentAgencyTimeUnits

from .base import render


def generate(model: EnvironmentAgencyTimeUnits) -> str:
    return render("id_mapping/environment_agency_time_units.xml.j2", model)
