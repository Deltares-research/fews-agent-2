"""Transformations generator (the lightweight region-level lookup form;
distinct from the full transformation_module)."""
from __future__ import annotations

from fews_agent.schema import Transformations

from .base import render


def generate(model: Transformations) -> str:
    return render("region/transformations.xml.j2", model)
