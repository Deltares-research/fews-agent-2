"""WebOCMicroFrontEnds generator."""
from __future__ import annotations

from fews_agent.schema import WebOCMicroFrontEnds

from .base import render


def generate(model: WebOCMicroFrontEnds) -> str:
    return render("display/weboc_micro_frontends.xml.j2", model)
