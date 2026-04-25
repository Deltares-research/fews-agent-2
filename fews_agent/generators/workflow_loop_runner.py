"""WorkflowLoopRunner generator."""
from __future__ import annotations

from fews_agent.schema import WorkflowLoopRunner

from .base import render


def generate(model: WorkflowLoopRunner) -> str:
    return render("module/workflow_loop_runner.xml.j2", model)
