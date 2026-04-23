"""StorageBasinSystem generator."""
from __future__ import annotations

from fews_agent.schema import StorageBasinSystem

from .base import render


def generate(model: StorageBasinSystem) -> str:
    return render("region/storage_basin_system.xml.j2", model)
