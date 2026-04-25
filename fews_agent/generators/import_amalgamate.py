"""ImportAmalgamate generator."""
from __future__ import annotations

from fews_agent.schema import ImportAmalgamate

from .base import render


def generate(model: ImportAmalgamate) -> str:
    return render("module/import_amalgamate.xml.j2", model)
