"""Branches generator."""
from __future__ import annotations

from fews_agent.schema import Branches

from .base import render


def generate(model: Branches) -> str:
    return render("region/branches.xml.j2", model)
