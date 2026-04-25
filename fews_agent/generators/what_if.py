"""WhatIf generator."""
from __future__ import annotations

from fews_agent.schema import WhatIf

from .base import render


def generate(model: WhatIf) -> str:
    return render("region/what_if.xml.j2", model)
