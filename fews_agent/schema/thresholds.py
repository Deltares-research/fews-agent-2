"""Thresholds.xml — threshold groups and per-level severity mapping.

Declares thresholdGroupId and levelThresholdId; references warningLevelId
(declared in ThresholdWarningLevels).

`defaultThreshold` is a single element with just a shortName attribute
(points to one of the levelThreshold shortNames). The actual numeric
values per threshold live in ThresholdValueSets, keyed by levelThresholdId.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel, UnitMultiplier
from .ids import LevelThresholdId, ThresholdGroupId, WarningLevelId


class DefaultThreshold(FewsModel):
    """Points at a levelThreshold within the same group via its shortName."""

    shortName: str


class Season(FewsModel):
    """SeasonComplexType — a yearly recurring validity window for a
    threshold. monthDay attributes are raw ``--MM-DD`` strings."""

    startMonthDay: str
    endMonthDay: str
    timeZone: str | None = None
    label: str | None = None


class LevelThreshold(FewsModel):
    """One severity level. XSD: a choice of up/down warningLevelId, then
    optional deprecated up/down intIds and an optional season window."""

    id: LevelThresholdId
    # XSD choice (both optional): which crossing direction this level maps to.
    upWarningLevelId: WarningLevelId | None = None
    downWarningLevelId: WarningLevelId | None = None
    upIntId: int | None = None  # deprecated
    downIntId: int | None = None  # deprecated
    season: Season | None = None
    name: str | None = None
    shortName: str | None = None


class RateThreshold(FewsModel):
    """Rate-of-change threshold kind. Deprecated up/down intIds + season."""

    id: str
    name: str | None = None
    upIntId: int | None = None
    downIntId: int | None = None
    season: Season | None = None


class MaxThreshold(FewsModel):
    """Maximum-value threshold kind. Deprecated intId + season."""

    id: str
    name: str | None = None
    intId: int | None = None
    season: Season | None = None


class ThresholdGroup(FewsModel):
    """One threshold group. XSD ThresholdChoiceGroup permits any mix of
    levelThreshold / rateThreshold kinds plus an optional maxThreshold."""

    id: ThresholdGroupId
    name: str | None = None
    defaultThreshold: DefaultThreshold | None = None
    levelThreshold: list[LevelThreshold] = Field(default_factory=list)
    rateThreshold: list[RateThreshold] = Field(default_factory=list)
    maxThreshold: MaxThreshold | None = None


class ForecastAvailableThreshold(FewsModel):
    """Used to log that a forecast was available in a time window when
    the observed threshold crossed. Powers the SkillScoreDisplay."""

    id: str
    name: str | None = None
    intId: int | None = None  # deprecated


class ThresholdGroups(FewsModel):
    """Root of Thresholds.xml (the element is `thresholdGroups`, plural).

    XSD sequence: eventExpiryTime? maxActionEventDuration?
    forecastAvailableThreshold? thresholdGroup+.
    """

    thresholdGroup: list[ThresholdGroup] = Field(min_length=1)
    eventExpiryTime: UnitMultiplier | None = None
    maxActionEventDuration: UnitMultiplier | None = None
    forecastAvailableThreshold: ForecastAvailableThreshold | None = None
