"""PcrTransformationSets generator."""
from __future__ import annotations

from fews_agent.schema import PcrTransformationSets

from .base import render


def generate(model: PcrTransformationSets) -> str:
    return render("module/pcr_transformation_sets.xml.j2", model)
