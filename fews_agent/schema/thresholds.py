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


class LevelThreshold(FewsModel):
    id: LevelThresholdId
    upWarningLevelId: WarningLevelId
    name: str | None = None
    shortName: str | None = None


class ThresholdGroup(FewsModel):
    id: ThresholdGroupId
    name: str | None = None
    defaultThreshold: DefaultThreshold | None = None
    levelThreshold: list[LevelThreshold] = Field(min_length=1)


class ThresholdGroups(FewsModel):
    """Root of Thresholds.xml (the element is `thresholdGroups`, plural)."""

    thresholdGroup: list[ThresholdGroup] = Field(min_length=1)
    eventExpiryTime: UnitMultiplier | None = None
    maxActionEventDuration: UnitMultiplier | None = None
