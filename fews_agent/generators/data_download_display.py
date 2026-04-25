"""DataDownloadDisplay generator."""
from __future__ import annotations

from fews_agent.schema import DataDownloadDisplay

from .base import render


def generate(model: DataDownloadDisplay) -> str:
    return render("display/data_download_display.xml.j2", model)
