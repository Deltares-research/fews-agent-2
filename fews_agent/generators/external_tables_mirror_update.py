"""ExternalTablesMirrorUpdate generator."""
from __future__ import annotations

from fews_agent.schema import ExternalTablesMirrorUpdate

from .base import render


def generate(model: ExternalTablesMirrorUpdate) -> str:
    return render("module/external_tables_mirror_update.xml.j2", model)
