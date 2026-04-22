"""Workflow generator."""
from __future__ import annotations

from fews_agent.schema import Workflow

from .base import render


def generate(model: Workflow) -> str:
    return render("workflow.xml.j2", model)
