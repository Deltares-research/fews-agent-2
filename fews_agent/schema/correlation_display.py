"""CorrelationDisplay.xml — correlation scatter-plot UI.

Reuses CorrelationEquations from travel_times (same sharedTypes type).
Reuses RelativeViewPeriod from common.py (same underlying XSD type as
TimeSeriesSetRelativePeriodComplexType — see common.py docstring).
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import FewsModel, RelativeViewPeriod, TimeStep
from .travel_times import CorrelationEquations


class DisplayOptions(FewsModel):
    """XSD DisplayOptionsComplexType — chart styling."""

    preferredColor: str | None = None
    lineStyle: str | None = None
    markerStyle: str | None = None
    markerSize: int | None = None
    markerFilled: bool | None = None
    key: str | None = None


class ScatterPlotThresholdOptions(FewsModel):
    visible: bool


class ScatterPlotDisplayOptions(FewsModel):
    preferredColor: str | None = None
    lineStyle: str | None = None
    markerStyle: str | None = None
    markerSize: int | None = None
    markerFilled: bool | None = None
    thresholds: ScatterPlotThresholdOptions | None = None
    key: str | None = None


class CorrelationDisplayOptions(FewsModel):
    scatterplotOptions: ScatterPlotDisplayOptions
    equationOptions: DisplayOptions
    displayOptions: list[DisplayOptions] = Field(default_factory=list)


class TimeSeriesSetInfo(FewsModel):
    """Historic/forecast time-series descriptor (subset of TimeSeriesSet)."""

    parameterId: str
    moduleInstanceId: str | None = None
    qualifierId: list[str] = Field(default_factory=list)
    timeSeriesType: str | None = None
    timeStep: TimeStep | None = None
    relativeViewPeriod: RelativeViewPeriod | None = None
    readWriteMode: str | None = None


class ReferencePoint(FewsModel):
    x: float
    y: float


class ReferencePoints(FewsModel):
    """XSD choice: either inline point[] or xAttributeId/yAttributeId pair."""

    point: list[ReferencePoint] = Field(default_factory=list)
    xAttributeId: str | None = None
    yAttributeId: str | None = None

    @model_validator(mode="after")
    def _inline_xor_attrs(self) -> ReferencePoints:
        has_inline = bool(self.point)
        has_attrs = self.xAttributeId is not None or self.yAttributeId is not None
        if has_inline == has_attrs:
            raise ValueError(
                "referencePoints: supply inline point[] OR xAttributeId/yAttributeId, not both"
            )
        if has_attrs and (self.xAttributeId is None or self.yAttributeId is None):
            raise ValueError(
                "referencePoints: xAttributeId and yAttributeId must be supplied together"
            )
        return self


class UserDefinedRelation(FewsModel):
    id: str
    name: str | None = None
    referencePoints: ReferencePoints
    displayOptionKey: str | None = None
    comment: str | None = None


class CorrelationDisplay(FewsModel):
    """Root of CorrelationDisplay.xml."""

    inputTimeSerieInfo: TimeSeriesSetInfo
    eventSetsDescriptorId: str
    travelTimesDescriptorId: str
    eventSelectionType: Literal["eventid", "traveltime", "combined"]
    outputTimeSerieInfo: TimeSeriesSetInfo | None = None
    correlationDisplayOptions: CorrelationDisplayOptions | None = None
    defaultEquation: CorrelationEquations | None = None
    userDefinedRelation: list[UserDefinedRelation] = Field(default_factory=list)
    version: str = "1.1"
