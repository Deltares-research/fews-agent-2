"""ExportArchiveModule generator."""
from __future__ import annotations

from .base import render
from ..schema.export_archive_module import ExportArchiveModule


def generate(model: ExportArchiveModule) -> str:
    return render("module/export_archive_module.xml.j2", model)
