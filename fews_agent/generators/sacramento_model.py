"""SacramentoModel generator."""
from __future__ import annotations

from fews_agent.schema import SacramentoModel

from .base import render


def generate(model: SacramentoModel) -> str:
    return render("module/sacramento_model.xml.j2", model)
