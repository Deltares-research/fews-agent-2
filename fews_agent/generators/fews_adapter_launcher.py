"""FewsAdapterLauncher generator."""
from __future__ import annotations

from fews_agent.schema import FewsAdapterLauncher

from .base import render


def generate(model: FewsAdapterLauncher) -> str:
    return render("root/fews_adapter_launcher.xml.j2", model)
