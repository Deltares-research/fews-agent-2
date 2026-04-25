"""McSystemAlerter generator."""
from __future__ import annotations

from .base import render
from ..schema.mc_system_alerter import McSystemAlerter


def generate(model: McSystemAlerter) -> str:
    return render("system/mc_system_alerter.xml.j2", model)
