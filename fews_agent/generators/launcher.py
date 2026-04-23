"""Launcher generator."""
from __future__ import annotations

from fews_agent.schema import Launcher

from .base import render


def generate(model: Launcher) -> str:
    return render("root/launcher.xml.j2", model)
