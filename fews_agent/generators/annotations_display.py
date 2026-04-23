"""AnnotationsDisplay generator."""
from __future__ import annotations

from fews_agent.schema import AnnotationsDisplay

from .base import render


def generate(model: AnnotationsDisplay) -> str:
    return render("display/annotations_display.xml.j2", model)
