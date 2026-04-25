"""ConfigRevisionSet generator."""
from __future__ import annotations

from fews_agent.schema import ConfigRevisionSet

from .base import render


def generate(model: ConfigRevisionSet) -> str:
    return render("system/config_revision_set.xml.j2", model)
