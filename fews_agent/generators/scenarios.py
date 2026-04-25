"""Scenarios generator."""
from __future__ import annotations

from fews_agent.schema import Scenarios

from .base import render


def generate(model: Scenarios) -> str:
    return render("module/scenarios.xml.j2", model)
