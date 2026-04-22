"""ForecasterNotesDisplay generator."""
from __future__ import annotations

from fews_agent.schema import ForecasterNotesDisplay

from .base import render


def generate(model: ForecasterNotesDisplay) -> str:
    return render("forecaster_notes_display.xml.j2", model)
