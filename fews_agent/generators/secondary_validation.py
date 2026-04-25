"""SecondaryValidation generator."""
from __future__ import annotations

from .base import render
from ..schema.secondary_validation import SecondaryValidation


def generate(model: SecondaryValidation) -> str:
    return render("region/secondary_validation.xml.j2", model)
