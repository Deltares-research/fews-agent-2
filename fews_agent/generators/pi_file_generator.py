"""PiFileGenerator generator."""
from __future__ import annotations

from fews_agent.schema import PiFileGenerator

from .base import render


def generate(model: PiFileGenerator) -> str:
    return render("module/pi_file_generator.xml.j2", model)
