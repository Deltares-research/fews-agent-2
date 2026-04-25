"""FewsPiServiceConfig generator."""
from __future__ import annotations

from fews_agent.schema import FewsPiServiceConfig

from .base import render


def generate(model: FewsPiServiceConfig) -> str:
    return render("module/fews_pi_service_config.xml.j2", model)
