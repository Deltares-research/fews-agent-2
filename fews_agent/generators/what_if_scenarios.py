"""WhatIfScenarios generator (plural container)."""
from __future__ import annotations

from fews_agent.schema import WhatIfScenarios

from .base import render


def generate(model: WhatIfScenarios) -> str:
    return render("region/what_if_scenarios.xml.j2", model)
