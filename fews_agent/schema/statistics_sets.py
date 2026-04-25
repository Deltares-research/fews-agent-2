"""StatisticsSets.xml — statistical transforms from input to output variables."""
from __future__ import annotations

from pydantic import Field

from .common import DataVariable, FewsModel


class StandardStatistics(FewsModel):
    upperPercentage: int | None = None
    lowerPercentage: int | None = None


class MovingAverage(FewsModel):
    numberSamples: int


class StatisticalFunctions(FewsModel):
    """All three children optional — XSD doesn't require any to be set."""

    standard: StandardStatistics | None = None
    # `higherMoment` is an empty marker (NoAttributesOrData) — bool flag.
    higherMoment: bool | None = None
    movingAverage: MovingAverage | None = None


class StatisticsSet(FewsModel):
    inputVariable: DataVariable
    statisticalFunctions: StatisticalFunctions
    outputVariable: list[DataVariable] = Field(min_length=1)


class StatisticsSets(FewsModel):
    """Root of StatisticsSets.xml."""

    statisticsSet: list[StatisticsSet] = Field(min_length=1)
