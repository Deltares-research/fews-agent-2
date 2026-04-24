"""TaskList generator."""
from __future__ import annotations

from fews_agent.schema import TaskList

from .base import render


def generate(model: TaskList) -> str:
    return render("system/task_list.xml.j2", model)
