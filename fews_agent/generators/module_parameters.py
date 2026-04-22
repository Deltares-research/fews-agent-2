"""ModuleParameters generator (PI namespace)."""
from __future__ import annotations

from fews_agent.schema import ModuleParameters

from .base import render


def generate(model: ModuleParameters) -> str:
    return render("module_parameters.xml.j2", model)
