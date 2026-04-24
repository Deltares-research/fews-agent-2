"""TaskPropertiesPredefined generator."""
from __future__ import annotations

from fews_agent.schema import TaskPropertiesPredefined

from .base import render


def generate(model: TaskPropertiesPredefined) -> str:
    return render("system/task_properties_predefined.xml.j2", model)
