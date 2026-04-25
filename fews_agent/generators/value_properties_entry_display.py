"""ValuePropertiesEntryDisplay generator."""
from __future__ import annotations

from .base import render
from ..schema.value_properties_entry_display import ValuePropertiesEntryDisplay


def generate(model: ValuePropertiesEntryDisplay) -> str:
    return render("display/value_properties_entry_display.xml.j2", model)
