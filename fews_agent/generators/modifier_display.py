"""ModifierDisplay generator (tutorial file is ModifiersDisplay.xml)."""
from __future__ import annotations

from fews_agent.schema import ModifierDisplay

from .base import render


def generate(model: ModifierDisplay) -> str:
    return render("display/modifier_display.xml.j2", model)
