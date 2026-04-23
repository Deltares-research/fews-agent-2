"""OnTheFlyExpressionTimeSeries generator."""
from __future__ import annotations

from fews_agent.schema import OnTheFlyExpressionTimeSeries

from .base import render


def generate(model: OnTheFlyExpressionTimeSeries) -> str:
    return render("region/on_the_fly_expression_time_series.xml.j2", model)
