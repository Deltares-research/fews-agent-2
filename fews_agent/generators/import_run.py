"""ImportRun generator."""
from __future__ import annotations

from fews_agent.schema import ImportRun

from .base import render


def generate(model: ImportRun) -> str:
    return render("module/import_run.xml.j2", model)
