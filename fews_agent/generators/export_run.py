"""ExportRun generator."""
from __future__ import annotations

from fews_agent.schema import ExportRun

from .base import render


def generate(model: ExportRun) -> str:
    return render("module/export_run.xml.j2", model)
