"""ValidationRuleSets generator."""
from __future__ import annotations

from fews_agent.schema import ValidationRuleSets

from .base import render


def generate(model: ValidationRuleSets) -> str:
    return render("region/validation_rule_sets.xml.j2", model)
