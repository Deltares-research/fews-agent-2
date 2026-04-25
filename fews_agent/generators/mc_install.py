"""McInstall generator."""
from __future__ import annotations

from .base import render
from ..schema.mc_install import McInstall


def generate(model: McInstall) -> str:
    return render("system/mc_install.xml.j2", model)
