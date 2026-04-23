"""ConfigUpdateModule generator."""
from __future__ import annotations

from fews_agent.schema import ConfigUpdateModule

from .base import render


def generate(model: ConfigUpdateModule) -> str:
    return render("module/config_update_module.xml.j2", model)
