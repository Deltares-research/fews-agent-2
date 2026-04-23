"""ImportArchiveModule generator."""
from __future__ import annotations

from fews_agent.schema import ImportArchiveModule

from .base import render


def generate(model: ImportArchiveModule) -> str:
    return render("module/import_archive_module.xml.j2", model)
