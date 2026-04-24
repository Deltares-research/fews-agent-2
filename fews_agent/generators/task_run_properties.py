"""TaskRunProperties generator."""
from __future__ import annotations

from fews_agent.schema import TaskRunProperties

from .base import render


def generate(model: TaskRunProperties) -> str:
    return render("system/task_run_properties.xml.j2", model)
