"""SouthernTransferFunctions generator."""
from __future__ import annotations

from fews_agent.schema import SouthernTransferFunctions

from .base import render


def generate(model: SouthernTransferFunctions) -> str:
    return render("module/southern_transfer_functions.xml.j2", model)
