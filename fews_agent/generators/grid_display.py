"""GridDisplay generator."""
from __future__ import annotations

from .base import render
from ..schema.grid_display import GridDisplay


def generate(model: GridDisplay) -> str:
    return render("display/grid_display.xml.j2", model)
