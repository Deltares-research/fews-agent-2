"""TrendDisplay.xml — plot-group trend dialog config."""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel, TimeSeriesSet


class RelativeTime(FewsModel):
    """XSD RelativeTimeComplexType — single point relative to T0."""

    value: int
    unit: str
    description: str | None = None


class TrendDisplayGeneral(FewsModel):
    description: str | None = None
    displayName: str
    agoPeriodLength: RelativeTime
    thresholdId: str


class TrendGroupChild(FewsModel):
    foreignKey: str


class TrendGroup(FewsModel):
    """Each group has either timeSeriesSet[] or child[] — XSD choice."""

    id: str
    name: str | None = None
    description: str | None = None
    timeSeriesSet: list[TimeSeriesSet] = Field(default_factory=list)
    child: list[TrendGroupChild] = Field(default_factory=list)
    thresholdId: str | None = None

    @model_validator(mode="after")
    def _tss_xor_child(self) -> TrendGroup:
        has_tss = bool(self.timeSeriesSet)
        has_child = bool(self.child)
        if has_tss == has_child:
            raise ValueError(
                "trendGroup: supply exactly one of timeSeriesSet[] or child[]"
            )
        return self


class TrendDisplay(FewsModel):
    """Root of TrendDisplay.xml."""

    description: str | None = None
    general: TrendDisplayGeneral
    group: list[TrendGroup] = Field(min_length=1)
