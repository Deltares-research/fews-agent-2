"""ThresholdExport generator."""
from __future__ import annotations

from fews_agent.schema import ThresholdExportModule

from .base import render


def generate(model: ThresholdExportModule) -> str:
    return render("module/threshold_export.xml.j2", model)
