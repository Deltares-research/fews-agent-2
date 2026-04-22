"""TransformationModule generator — shared by Preprocess + DataProcessing files."""
from __future__ import annotations

from fews_agent.schema import TransformationModule

from .base import render


def generate(model: TransformationModule) -> str:
    return render("transformation_module.xml.j2", model)
