"""TransformationCoefficientSets generator."""
from __future__ import annotations

from .base import render
from ..schema.transformation_coefficient_sets import TransformationCoefficientSets


def generate(model: TransformationCoefficientSets) -> str:
    return render("region/transformation_coefficient_sets.xml.j2", model)
