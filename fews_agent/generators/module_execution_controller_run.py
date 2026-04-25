"""ModuleExecutionControllerRun generator."""
from __future__ import annotations

from fews_agent.schema import ModuleExecutionControllerRun

from .base import render


def generate(model: ModuleExecutionControllerRun) -> str:
    return render("module/module_execution_controller_run.xml.j2", model)
