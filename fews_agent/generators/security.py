"""Security generator."""
from __future__ import annotations

from fews_agent.schema import Security

from .base import render


def generate(model: Security) -> str:
    return render("root/security.xml.j2", model)
