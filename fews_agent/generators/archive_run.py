"""ArchiveRun generator."""
from __future__ import annotations

from fews_agent.schema import ArchiveRun

from .base import render


def generate(model: ArchiveRun) -> str:
    return render("module/archive_run.xml.j2", model)
