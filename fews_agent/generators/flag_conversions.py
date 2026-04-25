"""FlagConversions generator."""
from __future__ import annotations

from fews_agent.schema import FlagConversions

from .base import render


def generate(model: FlagConversions) -> str:
    return render("id_mapping/flag_conversions.xml.j2", model)
