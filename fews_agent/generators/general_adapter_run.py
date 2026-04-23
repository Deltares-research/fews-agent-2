"""GeneralAdapterRun generator — ModelRun and Maintenance module configs."""
from __future__ import annotations

from fews_agent.schema import GeneralAdapterRun

from .base import render


def generate(model: GeneralAdapterRun) -> str:
    return render("module/general_adapter_run.xml.j2", model)
