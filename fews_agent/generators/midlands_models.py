"""MidlandsModels generator."""
from __future__ import annotations

from fews_agent.schema import MidlandsModel

from .base import render


def generate(model: MidlandsModel) -> str:
    return render("module/midlands_models.xml.j2", model)
