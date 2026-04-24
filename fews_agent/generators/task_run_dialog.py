"""TaskRunDialog generator."""
from __future__ import annotations

from fews_agent.schema import TaskRunDialog

from .base import render


def generate(model: TaskRunDialog) -> str:
    return render("display/task_run_dialog.xml.j2", model)
