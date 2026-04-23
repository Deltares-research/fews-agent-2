"""ModuleRunTableDisplay generator."""
from __future__ import annotations

from fews_agent.schema import ModuleRunTableDisplay

from .base import render


def generate(model: ModuleRunTableDisplay) -> str:
    return render("display/module_run_table_display.xml.j2", model)
