"""UserGroups generator."""
from __future__ import annotations

from fews_agent.schema import UserGroups

from .base import render


def generate(model: UserGroups) -> str:
    return render("user_groups.xml.j2", model)
