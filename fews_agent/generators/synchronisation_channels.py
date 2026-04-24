"""SynchronisationChannels generator."""
from __future__ import annotations

from fews_agent.schema import SynchronisationChannels

from .base import render


def generate(model: SynchronisationChannels) -> str:
    return render("system/synchronisation_channels.xml.j2", model)
