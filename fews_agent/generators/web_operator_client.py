"""WebOperatorClient generator."""
from __future__ import annotations

from .base import render
from ..schema.web_operator_client import WebOperatorClient


def generate(model: WebOperatorClient) -> str:
    return render("system/web_operator_client.xml.j2", model)
