"""FewsInstallationConfigurator generator."""
from __future__ import annotations

from fews_agent.schema import FewsInstallationConfigurator

from .base import render


def generate(model: FewsInstallationConfigurator) -> str:
    return render("root/fews_installation_configurator.xml.j2", model)
