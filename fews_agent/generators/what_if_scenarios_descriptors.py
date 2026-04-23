"""WhatIfScenariosDescriptors generator."""
from __future__ import annotations

from fews_agent.schema import WhatIfScenariosDescriptors

from .base import render


def generate(model: WhatIfScenariosDescriptors) -> str:
    return render("region/what_if_scenarios_descriptors.xml.j2", model)
