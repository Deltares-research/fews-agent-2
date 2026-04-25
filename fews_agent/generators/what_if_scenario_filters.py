"""WhatIfScenarioFilters generator."""
from __future__ import annotations

from fews_agent.schema import WhatIfScenarioFilters

from .base import render


def generate(model: WhatIfScenarioFilters) -> str:
    return render("region/what_if_scenario_filters.xml.j2", model)
