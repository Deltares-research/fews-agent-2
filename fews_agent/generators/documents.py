"""Documents generator."""
from __future__ import annotations

from fews_agent.schema import Documents

from .base import render


def generate(model: Documents) -> str:
    return render("region/documents.xml.j2", model)
