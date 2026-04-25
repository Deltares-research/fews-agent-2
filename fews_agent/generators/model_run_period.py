"""ModelRunPeriod generator."""
from __future__ import annotations

from fews_agent.schema import ModelRunPeriod

from .base import render


def generate(model: ModelRunPeriod) -> str:
    return render("root/model_run_period.xml.j2", model)
