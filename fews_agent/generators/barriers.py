"""Barriers generator."""
from __future__ import annotations

from fews_agent.schema import Barriers

from .base import render


def generate(model: Barriers) -> str:
    return render("module/barriers.xml.j2", model)
