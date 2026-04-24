"""RatingCurves generator."""
from __future__ import annotations

from fews_agent.schema import RatingCurves

from .base import render


def generate(model: RatingCurves) -> str:
    return render("region/rating_curves.xml.j2", model)
