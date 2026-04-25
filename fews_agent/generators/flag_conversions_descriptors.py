"""FlagConversionsDescriptors generator."""
from __future__ import annotations

from fews_agent.schema import FlagConversionsDescriptors

from .base import render


def generate(model: FlagConversionsDescriptors) -> str:
    return render("id_mapping/flag_conversions_descriptors.xml.j2", model)
