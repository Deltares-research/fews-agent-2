"""TimeSeriesModifiers.xml — top-level list of time-series modifier
groups, each tying a modifier id to one or more TimeSeriesSets.

XSD spells the child element with a capital T (``<TimeSeriesModifier>``).
We reflect that verbatim in the template; the Pydantic field name
is ``timeSeriesModifier`` (snake-ish) with an alias to the capital form.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel, TimeSeriesSet


class TimeSeriesModifierEntry(FewsModel):
    id: str
    timeSeriesSet: list[TimeSeriesSet] = Field(min_length=1)


class TimeSeriesModifiers(FewsModel):
    """Root of TimeSeriesModifiers.xml."""

    timeSeriesModifier: list[TimeSeriesModifierEntry] = Field(
        default_factory=list, alias="TimeSeriesModifier"
    )
