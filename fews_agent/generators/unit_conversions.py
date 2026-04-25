"""UnitConversions generator (shared by Import/Export/ExportRaven files)."""
from __future__ import annotations

from fews_agent.schema import UnitConversions

from .base import render


def generate(model: UnitConversions) -> str:
    return render("id_mapping/unit_conversions.xml.j2", model)
