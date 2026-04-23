"""RibasimModel generator."""
from __future__ import annotations

from fews_agent.schema import RibasimModel

from .base import render


def generate(model: RibasimModel) -> str:
    return render("module/ribasim_model.xml.j2", model)
