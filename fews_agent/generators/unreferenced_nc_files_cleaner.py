"""UnreferencedNcFilesCleaner generator."""
from __future__ import annotations

from fews_agent.schema import UnreferencedNcFilesCleaner

from .base import render


def generate(model: UnreferencedNcFilesCleaner) -> str:
    return render("module/unreferenced_nc_files_cleaner.xml.j2", model)
