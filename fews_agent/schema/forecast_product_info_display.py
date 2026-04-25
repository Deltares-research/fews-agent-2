"""ForecastProductInfoDisplay.xml — UI for the forecast product info panel."""
from __future__ import annotations

from typing import Literal

from .common import FewsModel, UnitMultiplier


class ForecastProductInfoColumn(FewsModel):
    visibleByDefault: bool | None = None


class ForecastProductInfoColumns(FewsModel):
    name: ForecastProductInfoColumn | None = None
    forecastTime: ForecastProductInfoColumn | None = None
    productTime: ForecastProductInfoColumn | None = None
    user: ForecastProductInfoColumn | None = None
    modificationTime: ForecastProductInfoColumn | None = None
    confidence: ForecastProductInfoColumn | None = None
    comment: ForecastProductInfoColumn | None = None
    classification: ForecastProductInfoColumn | None = None
    disapproved: ForecastProductInfoColumn | None = None


class ProductSelection(FewsModel):
    enabled: bool | None = None


class ClassificationToggle(FewsModel):
    enabled: bool | None = None


class Confidence(FewsModel):
    enabled: bool | None = None
    defaultLevel: Literal["LOW", "MEDIUM", "HIGH"] | None = None


class ForecastProductInfoForecastTime(FewsModel):
    enabled: bool | None = None
    defaultForecastTimeSelection: Literal["SINGLE", "RANGE"] | None = None
    defaultForecastPeriod: UnitMultiplier | None = None


class ForecastProductInfoDisplay(FewsModel):
    """Root of ForecastProductInfoDisplay.xml."""

    productSelection: ProductSelection | None = None
    forecastTime: ForecastProductInfoForecastTime | None = None
    confidence: Confidence | None = None
    classification: ClassificationToggle | None = None
    columns: ForecastProductInfoColumns | None = None
