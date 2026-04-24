"""ReservoirModel generator."""
from __future__ import annotations

from fews_agent.schema import ReservoirModel

from .base import render


def generate(model: ReservoirModel) -> str:
    return render("module/reservoir_model.xml.j2", model)
