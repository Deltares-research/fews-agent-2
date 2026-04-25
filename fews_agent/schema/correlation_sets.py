"""CorrelationSets.xml — correlations per forecast location.

Each ``<correlationSet>`` binds input time series to a forecast time
series through a correlation (equation + optional event/threshold/tag
selection criteria).
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import FewsModel, RelativeViewPeriod, TimeSeriesSet
from .travel_times import CorrelationEquations


EventSelectionType = Literal["eventid", "traveltime"]
TagOperator = Literal["and", "nand", "nor", "not", "or", "xor"]


class SelectionPeriod(FewsModel):
    startDate: str  # XSD date
    endDate: str
    selectInsidePeriod: bool
    startTime: str | None = None
    endTime: str | None = None


class SelectionThreshold(FewsModel):
    thresholdLimit: float
    selectAboveLimit: bool


class SelectionTags(FewsModel):
    """XSD choice at end: include (bool) XOR operator (enum)."""

    tag: list[str] = Field(min_length=1)
    include: bool | None = None
    operator: TagOperator | None = None

    @model_validator(mode="after")
    def _one_tail(self) -> SelectionTags:
        if (self.include is None) == (self.operator is None):
            raise ValueError(
                "selectionTags: supply exactly one of include or operator"
            )
        return self


class SelectionCriteria(FewsModel):
    period: SelectionPeriod | None = None
    thresholds: SelectionThreshold | None = None
    tags: SelectionTags | None = None
    travelTimes: RelativeViewPeriod | None = None


class Correlation(FewsModel):
    forecastLocationId: str
    equationType: CorrelationEquations
    eventSetsDescriptorId: str
    travelTimesDescriptorId: str
    eventSelectionType: EventSelectionType
    selectionCriteria: SelectionCriteria | None = None
    comment: str | None = None


class CorrelationSet(FewsModel):
    inputTimeSerieSet: list[TimeSeriesSet] = Field(min_length=1)
    correlation: Correlation
    outputTimeSerieSet: TimeSeriesSet


class CorrelationSets(FewsModel):
    version: str = "1.1"
    correlationSet: list[CorrelationSet] = Field(min_length=1)
