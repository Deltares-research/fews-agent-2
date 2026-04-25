"""Priorities (priorityList) generator."""
from __future__ import annotations

from fews_agent.schema import Priorities

from .base import render


def generate(model: Priorities) -> str:
    return render("region/priority_list.xml.j2", model)
