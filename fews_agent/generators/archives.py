"""Archives generator."""
from __future__ import annotations

from .base import render
from ..schema.archives import Archives


def generate(model: Archives) -> str:
    return render("system/archives.xml.j2", model)
