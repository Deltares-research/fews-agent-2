"""WebOCDashboards generator."""
from __future__ import annotations

from fews_agent.schema import WebOCDashboards

from .base import render


def generate(model: WebOCDashboards) -> str:
    return render("display/web_oc_dashboards.xml.j2", model)
