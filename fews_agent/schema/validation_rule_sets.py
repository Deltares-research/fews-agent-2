"""ValidationRuleSets.xml — data-quality rules applied to time series.

Each rule set scopes a set of time series and attaches extreme-value
bounds. `validationRuleSetId` is an attribute on the element (unlike
most FEWS registry files where `id` is used).
"""
from __future__ import annotations

from pydantic import Field

from .common import ExtremeValues, FewsModel, TimeSeriesSet
from .ids import ValidationRuleSetId


class ValidationRuleSet(FewsModel):
    validationRuleSetId: ValidationRuleSetId
    timeZone: str | None = None
    extremeValues: ExtremeValues | None = None
    timeSeriesSet: list[TimeSeriesSet] = Field(min_length=1)


class ValidationRuleSets(FewsModel):
    """Root of ValidationRuleSets.xml."""

    validationRuleSet: list[ValidationRuleSet] = Field(min_length=1)
    version: str = "1.1"
