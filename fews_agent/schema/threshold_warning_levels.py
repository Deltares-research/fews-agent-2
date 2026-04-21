"""ThresholdWarningLevels.xml — visual mapping of warning severity levels.

Declares warningLevelId referenced from Thresholds.levelThreshold.upWarningLevelId.
Typical content: 0 (No threshold) through 2+ (escalating severity).
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel
from .ids import WarningLevelId


class ThresholdWarningLevel(FewsModel):
    # id is a numeric-looking string ("0", "1", "2"). Treated as a plain
    # ID — validation (non-empty, trimmed) is handled by WarningLevelId.
    id: WarningLevelId
    color: str
    name: str | None = None
    iconName: str | None = None
    historicOverlayIconName: str | None = None
    forecastOverlayIconName: str | None = None


class ThresholdWarningLevels(FewsModel):
    """Root of ThresholdWarningLevels.xml."""

    thresholdWarningLevel: list[ThresholdWarningLevel] = Field(min_length=1)
