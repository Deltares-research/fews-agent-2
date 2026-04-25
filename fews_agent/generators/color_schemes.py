"""ColorSchemes generator."""
from __future__ import annotations

from .base import render
from ..schema.color_schemes import ColorSchemes


def generate(model: ColorSchemes) -> str:
    return render("system/color_schemes.xml.j2", model)
