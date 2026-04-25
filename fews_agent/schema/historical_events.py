"""HistoricalEvents.xml — reference historic events for validation/display.

Models the defined-data form of <eventData> (the snippet form). The
<timeSeriesSet> and harmonic <component> alternatives exist in the XSD
but aren't modeled yet.

The XSD defines <choice maxOccurs="unbounded"> over historicalEvent vs.
historicalEventSet, i.e. arbitrary interleaving. We represent them as
two parallel lists and emit historicalEvent entries before sets —
tutorial-style files are homogeneous, so this covers the common case.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import Field, model_validator

from .common import FewsModel, RelativeViewPeriod, TimeSeriesSet, TimeStep, TimeZone
from .ids import LocationId, ParameterId


class EventDataPoint(FewsModel):
    """One <data> element. XSD requires exactly value; date/time is one of
    dateTime / time / monthDay (all optional at schema level — FEWS picks
    whichever is supplied)."""

    dateTime: str | None = None
    time: str | None = None
    monthDay: str | None = None
    dayofWeek: str | None = None
    monthofYear: str | None = None
    # Decimal to preserve source digits ("2.196" must not become "2.1960000001").
    value: Decimal
    comment: str | None = None


class EventData(FewsModel):
    """XSD VariableComplexType — eventData can take three forms:
      1. Defined-data (timeStep + relativeViewPeriod + data[] + timeZone)
      2. External (timeSeriesSet reference)
      3. Harmonic (component list)
    Only the first is typed fully; the other two accept dict passthroughs.
    Carries three optional attributes (variableId, variableType, convertDatum).
    """

    # Attributes
    variableId: str | None = None
    variableType: str | None = None
    convertDatum: bool | None = None
    # Elements (choice between three branches)
    timeStep: TimeStep | None = None
    relativeViewPeriod: RelativeViewPeriod | None = None
    data: list[EventDataPoint] = Field(default_factory=list)
    timeZone: TimeZone | None = None
    timeSeriesSet: list[TimeSeriesSet] = Field(default_factory=list)
    component: list[dict[str, Any]] = Field(default_factory=list)


class HistoricalEvent(FewsModel):
    locationId: LocationId
    parameterId: ParameterId
    name: str
    eventData: EventData


class HistoricalEventSet(FewsModel):
    name: str
    historicalEvent: list[HistoricalEvent] = Field(min_length=1)


class HistoricalEvents(FewsModel):
    """Root of HistoricalEvents.xml. At least one event or set required."""

    historicalEvent: list[HistoricalEvent] = Field(default_factory=list)
    historicalEventSet: list[HistoricalEventSet] = Field(default_factory=list)
    version: str = "1.0"

    @model_validator(mode="after")
    def _at_least_one(self) -> HistoricalEvents:
        if not self.historicalEvent and not self.historicalEventSet:
            raise ValueError(
                "historicalEvents: supply at least one historicalEvent or historicalEventSet"
            )
        return self
