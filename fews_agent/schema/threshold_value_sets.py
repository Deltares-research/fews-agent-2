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

from pydantic import Field

from .common import FewsModel, TimeSeriesSet
from .ids import LevelThresholdId, ParameterId, ThresholdValueSetId


class LevelThresholdValue(FewsModel):
    levelThresholdId: LevelThresholdId
    valueFunction: str


class StageDischargeConversion(FewsModel):
    """Links stage series to a discharge parameter for H<->Q translation."""

    dischargeParameterId: ParameterId


class ThresholdValueSet(FewsModel):
    id: ThresholdValueSetId
    name: str | None = None
    levelThresholdValue: list[LevelThresholdValue] = Field(min_length=1)
    timeSeriesSet: list[TimeSeriesSet] = Field(default_factory=list)
    stageDischargeConversion: StageDischargeConversion | None = None


class ThresholdValueSets(FewsModel):
    """Root of ThresholdValueSets.xml."""

    thresholdValueSet: list[ThresholdValueSet] = Field(min_length=1)
