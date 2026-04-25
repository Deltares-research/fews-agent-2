"""UnitConversionsDescriptors generator."""
from __future__ import annotations

from fews_agent.schema import UnitConversionsDescriptors

from .base import render


def generate(model: UnitConversionsDescriptors) -> str:
    return render("id_mapping/unit_conversions_descriptors.xml.j2", model)
