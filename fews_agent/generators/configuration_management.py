"""ConfigurationManagement generator."""
from __future__ import annotations

from fews_agent.schema import ConfigurationManagement

from .base import render


def generate(model: ConfigurationManagement) -> str:
    return render("system/configuration_management.xml.j2", model)
