"""WhatIfScenario generator."""
from __future__ import annotations

from fews_agent.schema import WhatIfScenario

from .base import render


def generate(model: WhatIfScenario) -> str:
    return render("region/what_if_scenario.xml.j2", model)
