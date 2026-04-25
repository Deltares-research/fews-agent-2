"""TransformationSets generator."""
from __future__ import annotations

from .base import render
from ..schema.transformation_sets import TransformationSets


def generate(model: TransformationSets) -> str:
    return render("region/transformation_sets.xml.j2", model)
