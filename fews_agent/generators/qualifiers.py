"""Qualifiers generator."""
from __future__ import annotations

from fews_agent.schema import Qualifiers

from .base import render


def generate(model: Qualifiers) -> str:
    return render("region/qualifiers.xml.j2", model)
