"""SobekModel generator."""
from __future__ import annotations

from fews_agent.schema import SobekModel

from .base import render


def generate(model: SobekModel) -> str:
    return render("module/sobek_model.xml.j2", model)
