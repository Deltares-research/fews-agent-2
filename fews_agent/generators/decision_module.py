"""DecisionModule generator."""
from __future__ import annotations

from fews_agent.schema import DecisionModule

from .base import render


def generate(model: DecisionModule) -> str:
    return render("module/decision_module.xml.j2", model)
