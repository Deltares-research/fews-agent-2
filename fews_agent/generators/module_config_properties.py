"""ModuleConfigProperties generator."""
from __future__ import annotations

from fews_agent.schema import ModuleConfigProperties

from .base import render


def generate(model: ModuleConfigProperties) -> str:
    return render("region/module_config_properties.xml.j2", model)
