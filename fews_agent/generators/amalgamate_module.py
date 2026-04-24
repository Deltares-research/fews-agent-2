"""AmalgamateModule generator."""
from __future__ import annotations

from fews_agent.schema import AmalgamateModule

from .base import render


def generate(model: AmalgamateModule) -> str:
    return render("module/amalgamate_module.xml.j2", model)
