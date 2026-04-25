"""WhatIfScenarioEditor generator."""
from __future__ import annotations

from .base import render
from ..schema.what_if_scenario_editor import WhatIfScenarioEditor


def generate(model: WhatIfScenarioEditor) -> str:
    return render("region/what_if_scenario_editor.xml.j2", model)
