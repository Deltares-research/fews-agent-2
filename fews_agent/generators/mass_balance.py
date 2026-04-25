"""MassBalance generator."""
from __future__ import annotations

from fews_agent.schema import MassBalance

from .base import render


def generate(model: MassBalance) -> str:
    return render("module/mass_balance.xml.j2", model)
