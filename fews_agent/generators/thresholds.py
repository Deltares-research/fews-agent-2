"""Thresholds generator."""
from __future__ import annotations

from fews_agent.schema import ThresholdGroups

from .base import render


def generate(model: ThresholdGroups) -> str:
    return render("region/thresholds.xml.j2", model)
