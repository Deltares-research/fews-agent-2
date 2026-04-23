"""ContentUpdateChecker generator."""
from __future__ import annotations

from fews_agent.schema import ContentUpdateChecker

from .base import render


def generate(model: ContentUpdateChecker) -> str:
    return render("module/content_update_checker.xml.j2", model)
