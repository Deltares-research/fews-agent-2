"""ArchiveModuleDisplay generator."""
from __future__ import annotations

from fews_agent.schema import ArchiveModuleDisplay

from .base import render


def generate(model: ArchiveModuleDisplay) -> str:
    return render("display/archive_module_display.xml.j2", model)
