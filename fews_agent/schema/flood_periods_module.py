"""FloodPeriodsModule.xml — detects flood periods from threshold crossings.

XSD references CalendarTimeSpanComplexType, TimeSpanComplexType and
RelativePeriodComplexType. In practice (see wiki snippet) those three
collapse to the same `<elem unit="X" multiplier="N"/>` or
`<elem unit="X" start="S" end="E"/>` surface we already model as
UnitMultiplier and RelativeViewPeriod.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel, RelativeViewPeriod, TimeSeriesSet, UnitMultiplier


class ThresholdPropertyValueMap(FewsModel):
    value: str
    thresholdId: str


class ThresholdProperty(FewsModel):
    key: str
    map: list[ThresholdPropertyValueMap] = Field(min_length=1)


class ThresholdValuesSetsCrossings(FewsModel):
    thresholdGroupId: str | None = None
    timeSeriesSet: list[TimeSeriesSet] = Field(default_factory=list)


class ImportedThresholdCrossings(FewsModel):
    timeSeriesProperty: ThresholdProperty
    timeSeriesSet: list[TimeSeriesSet] = Field(default_factory=list)


class FloodPeriodThresholdCrossings(FewsModel):
    thresholdValuesSetsCrossings: list[ThresholdValuesSetsCrossings] = Field(default_factory=list)
    importedThresholdCrossings: list[ImportedThresholdCrossings] = Field(default_factory=list)


class FloodPeriodsModule(FewsModel):
    """Root of FloodPeriodsModule.xml."""

    newFloodPeriodLogEventCode: str
    areaLocationAttributeId: str
    skipLocationsWithoutAreaId: bool
    expiryTime: UnitMultiplier
    periodInitialLength: UnitMultiplier
    maximumPeriodExtensionLength: UnitMultiplier
    forecastSearchPeriod: RelativeViewPeriod | None = None
    observed: FloodPeriodThresholdCrossings
    forecasted: FloodPeriodThresholdCrossings
