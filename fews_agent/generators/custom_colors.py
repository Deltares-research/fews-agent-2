"""CustomColors generator."""
from __future__ import annotations

from fews_agent.schema import CustomColors

from .base import render


def generate(model: CustomColors) -> str:
    return render("system/custom_colors.xml.j2", model)
