"""LookUpSets generator."""
from __future__ import annotations

from fews_agent.schema import LookUpSets

from .base import render


def generate(model: LookUpSets) -> str:
    return render("region/lookup_sets.xml.j2", model)
