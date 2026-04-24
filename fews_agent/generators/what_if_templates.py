"""WhatIfTemplates generator."""
from __future__ import annotations

from fews_agent.schema import WhatIfTemplates

from .base import render


def generate(model: WhatIfTemplates) -> str:
    return render("region/what_if_templates.xml.j2", model)
