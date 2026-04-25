"""ThresholdEventsDisplay.xml — threshold events tab configuration."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel, TimeSeriesSet


class ThresholdEventsDisplay(FewsModel):
    """Root of ThresholdEventsDisplay.xml."""

    timeSeriesSet: list[TimeSeriesSet] = Field(min_length=1)
