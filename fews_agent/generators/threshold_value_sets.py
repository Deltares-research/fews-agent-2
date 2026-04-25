"""ThresholdValueSets generator."""
from __future__ import annotations

from fews_agent.schema import ThresholdValueSets

from .base import render


def generate(model: ThresholdValueSets) -> str:
    return render("region/threshold_value_sets.xml.j2", model)
