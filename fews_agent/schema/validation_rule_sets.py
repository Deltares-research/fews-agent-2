"""ValidationRuleSets.xml — data-quality rules applied to time series.

Each rule set scopes a set of time series and attaches extreme-value
bounds. `validationRuleSetId` is an attribute on the element (unlike
most FEWS registry files where `id` is used).
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import ExtremeValues, FewsModel, TimeSeriesSet
from .ids import ValidationRuleSetId


class ValidationRuleSet(FewsModel):
    # Attributes
    validationRuleSetId: ValidationRuleSetId
    timeZone: str | None = None
    # Elements in XSD sequence order
    logLevel: str | None = None
    unit: str | None = None
    considerQualifiers: bool | None = None
    # Choice: extremeValues | extremeValuesFunctions
    extremeValues: ExtremeValues | None = None
    extremeValuesFunctions: dict[str, Any] | None = None
    # Choice: rateOfChange | rateOfChangeFunctions | rateOfChangeTimeSpan | rateOfChangeFunctionsTimeSpan
    rateOfChange: list[dict[str, Any]] = Field(default_factory=list)
    rateOfChangeFunctions: list[dict[str, Any]] = Field(default_factory=list)
    rateOfChangeTimeSpan: list[dict[str, Any]] = Field(default_factory=list)
    rateOfChangeFunctionsTimeSpan: list[dict[str, Any]] = Field(default_factory=list)
    # Choice: sameReading | sameReadingFunctions
    sameReading: list[dict[str, Any]] = Field(default_factory=list)
    sameReadingFunctions: list[dict[str, Any]] = Field(default_factory=list)
    # Choice: temporaryShift | temporaryShiftFunctions
    temporaryShift: list[dict[str, Any]] = Field(default_factory=list)
    temporaryShiftFunctions: list[dict[str, Any]] = Field(default_factory=list)
    # Choice: oscillation | oscillationFunctions
    oscillation: list[dict[str, Any]] = Field(default_factory=list)
    oscillationFunctions: list[dict[str, Any]] = Field(default_factory=list)
    # Choice: timeSeries (filter) | timeSeriesSet
    timeSeries: list[dict[str, Any]] = Field(default_factory=list)
    timeSeriesSet: list[TimeSeriesSet] = Field(default_factory=list)


class ValidationRuleSets(FewsModel):
    """Root of ValidationRuleSets.xml."""

    validationRuleSet: list[ValidationRuleSet] = Field(min_length=1)
    version: str = "1.1"
