"""SynchronisationConfiguration generator."""
from __future__ import annotations

from fews_agent.schema import SynchronisationConfiguration

from .base import render


def generate(model: SynchronisationConfiguration) -> str:
    return render("system/synchronisation_configuration.xml.j2", model)
