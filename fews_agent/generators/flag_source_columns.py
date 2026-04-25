"""FlagSourceColumns generator."""
from __future__ import annotations

from fews_agent.schema import FlagSourceColumns

from .base import render


def generate(model: FlagSourceColumns) -> str:
    return render("region/flag_source_columns.xml.j2", model)
