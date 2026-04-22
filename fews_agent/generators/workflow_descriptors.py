"""WorkflowDescriptors generator."""
from __future__ import annotations

from fews_agent.schema import WorkflowDescriptors

from .base import render


def generate(model: WorkflowDescriptors) -> str:
    return render("workflow_descriptors.xml.j2", model)
