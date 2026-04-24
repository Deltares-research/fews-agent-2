"""HbvModel generator."""
from __future__ import annotations

from fews_agent.schema import HbvModel

from .base import render


def generate(model: HbvModel) -> str:
    return render("module/hbv_model.xml.j2", model)
