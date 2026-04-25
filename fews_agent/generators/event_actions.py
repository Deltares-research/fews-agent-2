"""EventActions generator."""
from __future__ import annotations

from fews_agent.schema import EventActions

from .base import render


def generate(model: EventActions) -> str:
    return render("system/event_actions.xml.j2", model)
