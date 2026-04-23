"""WarningEntryDisplay.xml — time-series + editable valueProperty columns."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel, TimeSeriesSet


class WarningEntryValueProperty(FewsModel):
    id: str
    propertyType: str  # XSD: propertyTypeEnumStringType (string | int | double | bool | ...)
    name: str | None = None
    enumerationValue: list[str] = Field(default_factory=list)
    defaultValueAttributeId: str | None = None


class WarningEntryDisplay(FewsModel):
    """Root of WarningEntryDisplay.xml."""

    timeSeriesSet: TimeSeriesSet
    valueProperty: list[WarningEntryValueProperty] = Field(min_length=1)
