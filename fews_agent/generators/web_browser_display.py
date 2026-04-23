"""WebBrowserDisplay generator."""
from __future__ import annotations

from fews_agent.schema import WebBrowserDisplay

from .base import render


def generate(model: WebBrowserDisplay) -> str:
    return render("display/web_browser_display.xml.j2", model)
