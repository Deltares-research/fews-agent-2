"""WarningEntryDisplay generator."""
from __future__ import annotations

from fews_agent.schema import WarningEntryDisplay

from .base import render


def generate(model: WarningEntryDisplay) -> str:
    return render("display/warning_entry_display.xml.j2", model)
