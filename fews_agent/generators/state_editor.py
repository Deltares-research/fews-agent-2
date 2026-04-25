"""StateEditor generator."""
from __future__ import annotations

from fews_agent.schema import StateEditor

from .base import render


def generate(model: StateEditor) -> str:
    return render("display/state_editor.xml.j2", model)
