"""WebServices generator."""
from __future__ import annotations

from .base import render
from ..schema.web_services import WebServices


def generate(model: WebServices) -> str:
    return render("system/web_services.xml.j2", model)
