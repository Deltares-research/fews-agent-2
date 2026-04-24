"""RdbmsExport generator."""
from __future__ import annotations

from fews_agent.schema import RdbmsExport

from .base import render


def generate(model: RdbmsExport) -> str:
    return render("module/rdbms_export.xml.j2", model)
