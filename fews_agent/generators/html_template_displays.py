"""HtmlTemplateDisplays generator."""
from __future__ import annotations

from fews_agent.schema import HtmlTemplateDisplays

from .base import render


def generate(model: HtmlTemplateDisplays) -> str:
    return render("display/html_template_displays.xml.j2", model)
