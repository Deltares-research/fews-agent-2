"""WorkflowTestRun generator."""
from __future__ import annotations

from fews_agent.schema import WorkflowTestRun

from .base import render


def generate(model: WorkflowTestRun) -> str:
    return render("module/workflow_test_run.xml.j2", model)
