"""ModuleInstanceDescriptors generator."""
from __future__ import annotations

from fews_agent.schema import ModuleInstanceDescriptors

from .base import render


def generate(model: ModuleInstanceDescriptors) -> str:
    return render("region/module_instance_descriptors.xml.j2", model)
