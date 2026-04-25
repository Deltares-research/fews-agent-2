"""ModifierTypes generator."""
from __future__ import annotations

from fews_agent.schema import ModifierTypes

from .base import render


def generate(model: ModifierTypes) -> str:
    return render("region/modifier_types.xml.j2", model)
