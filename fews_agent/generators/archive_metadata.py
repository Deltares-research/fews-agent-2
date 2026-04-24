"""ArchiveMetaData generator."""
from __future__ import annotations

from fews_agent.schema import ArchiveMetaData

from .base import render


def generate(model: ArchiveMetaData) -> str:
    return render("system/archive_metadata.xml.j2", model)
