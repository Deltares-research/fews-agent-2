"""ModuleDescriptors generator."""
from __future__ import annotations

from fews_agent.schema import ModuleDescriptors

from .base import render


def generate(model: ModuleDescriptors) -> str:
    return render("static/module_descriptors.xml.j2", model)
