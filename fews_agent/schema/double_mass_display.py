"""DoubleMassDisplay.xml — double-mass analysis comparing observed vs.
base-group rainfall with an estimated homogenisation series."""
from __future__ import annotations

from .common import FewsModel, TimeSeriesSet


class DoubleMassDisplay(FewsModel):
    """Root of DoubleMassDisplay.xml."""

    modifierId: str
    baseGroupTimeSeriesSet: TimeSeriesSet
    observedTimeSeriesSet: TimeSeriesSet
    estimatedTimeSeriesSet: TimeSeriesSet
