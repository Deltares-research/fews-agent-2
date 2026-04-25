"""TabularConfigFilesDisplay generator."""
from __future__ import annotations

from fews_agent.schema import TabularConfigFilesDisplay

from .base import render


def generate(model: TabularConfigFilesDisplay) -> str:
    return render("display/tabular_config_files_display.xml.j2", model)
