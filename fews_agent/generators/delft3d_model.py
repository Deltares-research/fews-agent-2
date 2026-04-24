"""Delft3DModel generator."""
from __future__ import annotations

from fews_agent.schema import Delft3DModel

from .base import render


def generate(model: Delft3DModel) -> str:
    return render("module/delft3d_model.xml.j2", model)
