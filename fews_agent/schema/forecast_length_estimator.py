"""ForecastLengthEstimator (SetForecastLengthTemplate).

Calculates the forecast length / time-0 of a workflow run from input time
series, cold-state search, and a set of time-0 selection strategies.

The common case (used by the raven/wflow patterns and the bundled
``setForecastLengthTemplate.yaml``) is just one ``externalForecastTimeSeries``
plus a ``minForecastLength`` — that renders byte-identically. The full XSD
surface (state determination, multiple time-series roles, the time-0 choice,
forecast-time creation per data feed) is modelled here as optional fields.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from .common import (
    CalendarTimeSpan,
    FewsModel,
    RelativePeriod,
    RelativeTime,
    TimeSeriesSet,
    TimeStep,
    UnitMultiplier,
)
from .ids import ModuleInstanceId


def _as_list(v: Any) -> Any:
    """Wrap a single dict in a 1-element list (back-compat: callers and the
    bundled standard pass a single time-series-set dict where the XSD allows
    several)."""
    if isinstance(v, dict):
        return [v]
    return v


class ForecastLengthWarmState(FewsModel):
    """XSD WarmStateComplexType — state-search window used to determine the
    default/overruling start time when not in a general-adapter run.

    Named distinctly from ``general_adapter_run.WarmStateSelection`` (which
    models only ``stateSearchPeriod``); this carries the full warm-state
    surface used by the forecast-length estimator's state determination."""

    stateSearchPeriod: RelativePeriod
    searchForTransientStates: bool | None = None
    transientStateExpiryTime: CalendarTimeSpan | None = None
    coldStateTime: RelativeTime | None = None
    insertColdState: bool | None = None  # deprecated


class ColdStateTime(FewsModel):
    """XSD ColdStateTimeComplexType — `setColdStateTimeToEarliestNonMissing`."""

    timeSeriesSet: list[TimeSeriesSet] = Field(min_length=1)
    minColdStateRelativeTime: RelativeTime
    maxColdStateRelativeTime: RelativeTime

    @field_validator("timeSeriesSet", mode="before")
    @classmethod
    def _wrap(cls, v: Any) -> Any:
        return _as_list(v)


class SetToModifiedDateTimeAttributeValue(FewsModel):
    """Set time-0 to a modified date/time attribute value, with a fallback
    offset applied to the run's time-0 when no modifier exists."""

    attributeId: str
    locationId: str
    offset: UnitMultiplier
    timeStep: TimeStep


class CopyTimeSeriesPropertyToExternalForecastTime(FewsModel):
    """Copy an external forecast time from a time-series property into a
    named externalForecastTimeId for use later in the workflow."""

    timeSeriesSet: list[TimeSeriesSet] = Field(min_length=1)
    dateTimeFormat: str | None = None
    externalForecastTimeId: str
    timeSeriesPropertyKey: str

    @field_validator("timeSeriesSet", mode="before")
    @classmethod
    def _wrap(cls, v: Any) -> Any:
        return _as_list(v)


class DataFeed(FewsModel):
    """One data feed whose latest common external forecast time is logged."""

    timeSeriesSet: list[TimeSeriesSet] = Field(min_length=1)
    id: str

    @field_validator("timeSeriesSet", mode="before")
    @classmethod
    def _wrap(cls, v: Any) -> Any:
        return _as_list(v)


class CreateExternalForecastTime(FewsModel):
    """XSD CreateExternalForecastTimeComplexType —
    `findLatestCommonExternalForecastTime`."""

    eventCodeOnChange: str | None = None
    eventCodeOnNoChange: str | None = None
    dataFeed: list[DataFeed] = Field(min_length=1)
    externalForecastTimeId: str

    @field_validator("dataFeed", mode="before")
    @classmethod
    def _wrap(cls, v: Any) -> Any:
        return _as_list(v)


class ForecastLengthEstimator(FewsModel):
    """Root of SetForecastLength*.xml. All fields are optional at the XSD
    level; the common case supplies only ``externalForecastTimeSeries`` +
    ``minForecastLength``.

    The list-typed time-series fields accept a single dict for back-compat
    (wrapped into a 1-element list) so existing single-set configs render
    unchanged.
    """

    timeZone: str | None = None
    # Cold-state-time determination (XSD choice): either
    # setColdStateTimeToEarliestNonMissing OR the stateModuleInstanceId /
    # stateSelection / onlyIntermediateStates inner sequence.
    setColdStateTimeToEarliestNonMissing: ColdStateTime | None = None
    stateModuleInstanceId: ModuleInstanceId | None = None
    stateSelection: ForecastLengthWarmState | None = None
    onlyIntermediateStates: bool | None = None
    # Time-series roles (each optional, repeatable).
    externalHistoricalTimeSeries: list[TimeSeriesSet] = Field(default_factory=list)
    externalForecastTimeSeries: list[TimeSeriesSet] = Field(default_factory=list)
    simulatedForecastTimeSeries: list[TimeSeriesSet] = Field(default_factory=list)
    requiredExternalForecastTimeSeries: list[TimeSeriesSet] = Field(default_factory=list)
    copyTimeSeriesPropertyToExternalForecastTime: list[
        CopyTimeSeriesPropertyToExternalForecastTime
    ] = Field(default_factory=list)
    # Time-0 selection (XSD choice — at most one).
    setTime0ToEarliestExternalForecastTime: bool | None = None
    setTime0ToLatestExternalForecastTime: bool | None = None
    setTime0ToEarliestCurrentForecast: bool | None = None
    setToModifiedDateTimeAttributeValueComplexType: (
        SetToModifiedDateTimeAttributeValue | None
    ) = None
    setTime0ToCurrentTime: bool | None = None
    setTime0ToLatestNonMissing: bool | None = None
    shiftEndTimeAfterTime0Shift: bool | None = None
    time0CardinalTimeStep: TimeStep | None = None
    skipRunWhenTime0EqualToLastRun: bool | None = None
    skipRunWhenTimeSeriesMissing: bool | None = None
    ignoreCompletelyMissingTimeSeries: bool | None = None
    minForecastLength: UnitMultiplier | None = None
    maxForecastLength: UnitMultiplier | None = None
    minForecastEndDay: str | None = None
    useLongestTimeSeries: bool | None = None
    findLatestCommonExternalForecastTime: list[CreateExternalForecastTime] = Field(
        default_factory=list
    )

    @field_validator(
        "externalHistoricalTimeSeries",
        "externalForecastTimeSeries",
        "simulatedForecastTimeSeries",
        "requiredExternalForecastTimeSeries",
        mode="before",
    )
    @classmethod
    def _wrap_ts(cls, v: Any) -> Any:
        return _as_list(v)
