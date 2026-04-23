"""ColdModuleInstanceStateGroups generator."""
from __future__ import annotations

from fews_agent.schema import ColdModuleInstanceStateGroups

from .base import render


def generate(model: ColdModuleInstanceStateGroups) -> str:
    return render("region/cold_module_instance_state_groups.xml.j2", model)
