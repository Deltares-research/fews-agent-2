"""LogMessage generator."""
from __future__ import annotations

from fews_agent.schema import LogMessage

from .base import render


def generate(model: LogMessage) -> str:
    return render("system/log_message.xml.j2", model)
