"""AnnotationDisplay generator."""
from __future__ import annotations

from fews_agent.schema import AnnotationDisplay

from .base import render


def generate(model: AnnotationDisplay) -> str:
    return render("display/annotation_display.xml.j2", model)
