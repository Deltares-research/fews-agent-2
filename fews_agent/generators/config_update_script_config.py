"""ConfigUpdateScriptConfig generator."""
from __future__ import annotations

from fews_agent.schema import ConfigUpdateScriptConfig

from .base import render


def generate(model: ConfigUpdateScriptConfig) -> str:
    return render("system/config_update_script_config.xml.j2", model)
