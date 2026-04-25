"""ClientConfig generator."""
from __future__ import annotations

from .base import render
from ..schema.client_config import ClientConfig


def generate(model: ClientConfig) -> str:
    return render("system/client_config.xml.j2", model)
