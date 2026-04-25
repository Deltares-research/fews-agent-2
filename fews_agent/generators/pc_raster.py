"""PcRaster generator."""
from __future__ import annotations

from fews_agent.schema import PCRaster

from .base import render


def generate(model: PCRaster) -> str:
    return render("module/pc_raster.xml.j2", model)
