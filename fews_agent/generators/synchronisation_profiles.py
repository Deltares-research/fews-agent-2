"""SynchronisationProfiles generator."""
from __future__ import annotations

from fews_agent.schema import SynchronisationProfiles

from .base import render


def generate(model: SynchronisationProfiles) -> str:
    return render("system/synchronisation_profiles.xml.j2", model)
