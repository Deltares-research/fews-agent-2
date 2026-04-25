"""ModuleInstanceSets generator."""
from __future__ import annotations

from fews_agent.schema import ModuleInstanceSets

from .base import render


def generate(model: ModuleInstanceSets) -> str:
    return render("region/module_instance_sets.xml.j2", model)
