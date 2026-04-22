"""IdMap generator — shared by all 14 tutorial IdMap files."""
from __future__ import annotations

from fews_agent.schema import IdMap

from .base import render


def generate(model: IdMap) -> str:
    return render("id_map.xml.j2", model)
