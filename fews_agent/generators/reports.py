"""Reports generator."""
from __future__ import annotations

from .base import render
from ..schema.reports import Reports


def generate(model: Reports) -> str:
    return render("module/reports.xml.j2", model)
