"""ThresholdValueSets.xml — per-location numeric threshold values.

A ThresholdValueSet ties together:
  - the threshold levels it applies (by levelThresholdId -> Thresholds.xml)
  - the actual numeric values per level
  - the input time series it watches (timeSeriesSet[])
  - optional stage/discharge conversion

`valueFunction` is typically a numeric literal ("5", "10") but can be a
FEWS runtime placeholder like `@AlertLevel@` — so we model it as a
string and let FEWS resolve at runtime.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel, RelativePeriod, TimeSeriesSet
from .ids import LevelThresholdId, ParameterId, ThresholdValueSetId


class LevelThresholdValue(FewsModel):
    levelThresholdId: LevelThresholdId
    valueFunction: str


class StageDischargeConversion(FewsModel):
    """Links stage series to a discharge parameter for H<->Q translation."""

    dischargeParameterId: ParameterId


class ThresholdValueSet(FewsModel):
    # Attributes
    id: ThresholdValueSetId
    name: str | None = None
    # Elements in XSD sequence order
    description: str | None = None
    considerQualifiers: bool | None = None
    standDownIndividualLocations: bool | None = None
    locationAttributeId: list[str] = Field(default_factory=list)
    graceTime: dict[str, Any] | None = None
    # Alternate branch — stage/discharge (dict passthroughs for full XSD coverage)
    stage: dict[str, Any] | None = None
    discharge: dict[str, Any] | None = None
    # Common form — levelThresholdValue + timeSeries/timeSeriesSet
    levelThresholdValue: list[LevelThresholdValue] = Field(default_factory=list)
    forecastAvailableThresholdValue: dict[str, Any] | None = None
    timeSeries: list[dict[str, Any]] = Field(default_factory=list)
    timeSeriesSet: list[TimeSeriesSet] = Field(default_factory=list)
    stageDischargeConversion: StageDischargeConversion | None = None


class ThresholdValueSets(FewsModel):
    """Root of ThresholdValueSets.xml.

    ``eventTimeViewPeriod`` (since 2017.02) is the default view period
    used by the Threshold Events display; evaluated against FEWS system
    time at render.
    """

    thresholdValueSet: list[ThresholdValueSet] = Field(min_length=1)
    eventTimeViewPeriod: RelativePeriod | None = None
