"""Permissions generator."""
from __future__ import annotations

from fews_agent.schema import Permissions

from .base import render


def generate(model: Permissions) -> str:
    return render("system/permissions.xml.j2", model)
