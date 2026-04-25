"""Mc generator."""
from __future__ import annotations

from .base import render
from ..schema.mc import Mc


def generate(model: Mc) -> str:
    return render("system/mc.xml.j2", model)
