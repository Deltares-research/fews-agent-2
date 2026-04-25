"""CommonAdapter generator."""
from __future__ import annotations

from fews_agent.schema import CommonAdapter

from .base import render


def generate(model: CommonAdapter) -> str:
    return render("module/common_adapter.xml.j2", model)
