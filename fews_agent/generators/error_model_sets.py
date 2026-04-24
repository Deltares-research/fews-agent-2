"""ErrorModelSets generator."""
from __future__ import annotations

from fews_agent.schema import ErrorModelSets

from .base import render


def generate(model: ErrorModelSets) -> str:
    return render("region/error_model_sets.xml.j2", model)
