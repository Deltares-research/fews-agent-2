"""ConfigurationValidation generator."""
from __future__ import annotations

from fews_agent.schema import ConfigurationValidation

from .base import render


def generate(model: ConfigurationValidation) -> str:
    return render("system/configuration_validation.xml.j2", model)
