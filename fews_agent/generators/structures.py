"""Structures generator."""
from __future__ import annotations

from fews_agent.schema import Structures

from .base import render


def generate(model: Structures) -> str:
    return render("region/structures.xml.j2", model)
