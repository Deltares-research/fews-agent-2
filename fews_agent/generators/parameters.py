"""Parameters generator."""
from __future__ import annotations

from fews_agent.schema import Parameters

from .base import render


def generate(model: Parameters) -> str:
    return render("parameters.xml.j2", model)
