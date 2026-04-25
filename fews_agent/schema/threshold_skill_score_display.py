"""ThresholdSkillScoreDisplay.xml — verification display for threshold-
crossing skill scores between forecast and observed series.

XSD choice inside ``ThresholdSkillScoreAttributeComplexType``:
  - ``attributeMapId`` + ``attributeValue`` pair, OR
  - standalone ``color``.

XSD choice inside each ``group`` body:
  - ``timeSeriesSet+`` (optionally followed by ``locationDefaultCriteria*``),
    OR
  - ``child+`` (references to sub-group ids via ``foreignKey``).
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel, RelativeTime, TimeSeriesSet


class EventMatchingCriteria(FewsModel):
    """Four RelativeTime windows — all required (per XSD group)."""

    minTimeZeroDifference: RelativeTime
    maxTimeZeroDifference: RelativeTime
    earlyDifference: RelativeTime
    lateDifference: RelativeTime


class LocationEventMatchingCriteria(FewsModel):
    locationId: str
    minTimeZeroDifference: RelativeTime
    maxTimeZeroDifference: RelativeTime
    earlyDifference: RelativeTime
    lateDifference: RelativeTime


class ThresholdSkillScoreAttribute(FewsModel):
    """Choice: (attributeMapId + attributeValue) XOR standalone color."""

    attributeMapId: str | None = None
    attributeValue: float | None = None
    color: str | None = None

    @model_validator(mode="after")
    def _one_form(self) -> ThresholdSkillScoreAttribute:
        has_map = self.attributeMapId is not None or self.attributeValue is not None
        has_color = self.color is not None
        if has_map and has_color:
            raise ValueError(
                "thresholdSkillScoreAttribute: choose either (attributeMapId + "
                "attributeValue) or color, not both"
            )
        if has_map and (self.attributeMapId is None or self.attributeValue is None):
            raise ValueError(
                "thresholdSkillScoreAttribute: attributeMapId and attributeValue "
                "must be supplied together"
            )
        if not has_map and not has_color:
            raise ValueError(
                "thresholdSkillScoreAttribute: supply (attributeMapId + "
                "attributeValue) or color"
            )
        return self


class ThresholdSkillScoreParameterPair(FewsModel):
    parameterIdObs: str
    parameterIdFor: str


class ThresholdSkillScoreDisplayGeneral(FewsModel):
    description: str | None = None
    displayName: str
    levelThresholdId: list[str] = Field(default_factory=list)
    rateThresholdId: list[str] = Field(default_factory=list)
    maxThresholdId: list[str] = Field(default_factory=list)
    attributeMatching: ThresholdSkillScoreAttribute | None = None
    attributeMissingObserved: ThresholdSkillScoreAttribute | None = None
    attributeMissingForecast: ThresholdSkillScoreAttribute | None = None
    minTimeZeroDifference: RelativeTime
    maxTimeZeroDifference: RelativeTime
    earlyDifference: RelativeTime
    lateDifference: RelativeTime
    parameterPairs: list[ThresholdSkillScoreParameterPair] = Field(min_length=1)


class ThresholdSkillScoreGroupChild(FewsModel):
    foreignKey: str


class ThresholdSkillScoreGroup(FewsModel):
    """Repeating `<group>`. XSD choice at body: timeSeriesSet* (+ optional
    locationDefaultCriteria*) OR child+. Exactly one of those branches
    must be populated."""

    id: str
    name: str | None = None
    description: str | None = None
    groupDefaultCriteria: EventMatchingCriteria | None = None
    timeSeriesSet: list[TimeSeriesSet] = Field(default_factory=list)
    locationDefaultCriteria: list[LocationEventMatchingCriteria] = Field(
        default_factory=list
    )
    child: list[ThresholdSkillScoreGroupChild] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_branch(self) -> ThresholdSkillScoreGroup:
        ts_branch = bool(self.timeSeriesSet)
        child_branch = bool(self.child)
        if ts_branch and child_branch:
            raise ValueError(
                f"group {self.id!r}: pick either timeSeriesSet/locationDefaultCriteria "
                "or child, not both"
            )
        if not ts_branch and not child_branch:
            raise ValueError(
                f"group {self.id!r}: supply at least one timeSeriesSet or child"
            )
        if self.locationDefaultCriteria and not ts_branch:
            raise ValueError(
                f"group {self.id!r}: locationDefaultCriteria requires timeSeriesSet"
            )
        return self


class ThresholdSkillScoreDisplay(FewsModel):
    description: str | None = None
    general: ThresholdSkillScoreDisplayGeneral
    group: list[ThresholdSkillScoreGroup] = Field(min_length=1)
