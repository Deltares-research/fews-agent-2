"""DAFilter generator."""
from __future__ import annotations

from fews_agent.schema import DAFilter

from .base import render


def generate(model: DAFilter) -> str:
    return render("module/da_filter.xml.j2", model)
