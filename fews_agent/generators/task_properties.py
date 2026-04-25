"""TaskProperties generator."""
from __future__ import annotations

from fews_agent.schema import TaskProperties

from .base import render


def generate(model: TaskProperties) -> str:
    return render("system/task_properties.xml.j2", model)
