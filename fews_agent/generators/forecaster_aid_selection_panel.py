"""ForecasterAidSelectionPanel generator."""
from __future__ import annotations

from fews_agent.schema import ForecasterAidSelectionPanel

from .base import render


def generate(model: ForecasterAidSelectionPanel) -> str:
    return render("display/forecaster_aid_selection_panel.xml.j2", model)
