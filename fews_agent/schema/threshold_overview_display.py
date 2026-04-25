"""ThresholdOverviewDisplay.xml — threshold-overview GUI config.

``displayDescriptor`` can take two shapes:
  1. Legacy: forecastTime + optional attributeNoCrossing / attributeMissingValues
     / attributeMissingForecast + tab1 + tab2 + tab3 + optional tab4.
  2. New: one or more ``<thresholdCrossingCountsTab>``.

Modelled with a top-level validator enforcing the branch choice.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import DataVariable, FewsModel, RelativeViewPeriod, TimeStep


HighestThresholdLabelType = Literal[
    "parameter", "thresholdName", "levelThresholdValueLabel"
]
MultipleTimeSeriesHandlingType = Literal["add_crossing_counts"]


class ForecastFilter(FewsModel):
    workflowId: list[str] = Field(min_length=1)


class ThresholdOverviewDisplayGeneral(FewsModel):
    displayName: str
    description: str | None = None
    forecastFilter: ForecastFilter | None = None


class ForecastTime(FewsModel):
    columnName: str
    offsetVariable: str | None = None


class ThresholdOverviewAttribute(FewsModel):
    """Choice: (attributeMapId+attributeValue) XOR (color+text)."""

    attributeMapId: str | None = None
    attributeValue: float | None = None
    color: str | None = None
    text: str | None = None

    @model_validator(mode="after")
    def _one_form(self) -> ThresholdOverviewAttribute:
        map_branch = (
            self.attributeMapId is not None and self.attributeValue is not None
        )
        color_branch = self.color is not None and self.text is not None
        if map_branch == color_branch:
            raise ValueError(
                "thresholdOverviewAttribute: supply exactly one of "
                "(attributeMapId+attributeValue) or (color+text)"
            )
        # Guard against half-filled tuples
        if self.attributeMapId is not None and self.attributeValue is None:
            raise ValueError("attributeMapId requires attributeValue")
        if self.color is not None and self.text is None:
            raise ValueError("color requires text")
        return self


class Tab1(FewsModel):
    """Highest-alarms tab. Inner choice: columnHeader XOR
    dateTimeFormattingString; inner optional choice: displayThresholdName
    XOR displayLabel."""

    tabName: str
    columnVariable: str
    aggregationTimeStep: TimeStep
    description: str | None = None
    columnHeader: str | None = None
    dateTimeFormattingString: str | None = None
    displayThresholdName: bool | None = None
    displayLabel: HighestThresholdLabelType | None = None
    columnHeaderToolTipText: str | None = None
    columnWidth: int | None = None
    siteColumnWidth: int | None = None

    @model_validator(mode="after")
    def _choices(self) -> Tab1:
        if (self.columnHeader is None) == (self.dateTimeFormattingString is None):
            raise ValueError(
                "tab1: supply exactly one of columnHeader or dateTimeFormattingString"
            )
        if (
            self.displayThresholdName is not None
            and self.displayLabel is not None
        ):
            raise ValueError(
                "tab1: displayThresholdName and displayLabel are mutually exclusive"
            )
        return self


class Tab2(FewsModel):
    tabName: str
    aggregationTimeStep: TimeStep
    description: str | None = None
    columnWidth: int | None = None
    siteColumnWidth: int | None = None


class Tab3Column(FewsModel):
    visible: bool | None = None
    width: int | None = None


class Tab3(FewsModel):
    """Alarm summary. Choice: invisibleColumn[] (deprecated) XOR the
    eight column* structured fields."""

    tabName: str
    description: str | None = None
    invisibleColumn: list[int] = Field(default_factory=list)
    columnLocationId: Tab3Column | None = None
    columnLocationName: Tab3Column | None = None
    columnTime: Tab3Column | None = None
    columnParameter: Tab3Column | None = None
    columnValue: Tab3Column | None = None
    columnThresholdValue: Tab3Column | None = None
    columnThreshold: Tab3Column | None = None
    columnAction: Tab3Column | None = None

    @model_validator(mode="after")
    def _one_branch(self) -> Tab3:
        structured = [
            self.columnLocationId, self.columnLocationName, self.columnTime,
            self.columnParameter, self.columnValue, self.columnThresholdValue,
            self.columnThreshold, self.columnAction,
        ]
        any_structured = any(c is not None for c in structured)
        if self.invisibleColumn and any_structured:
            raise ValueError(
                "tab3: invisibleColumn and structured column* fields are "
                "mutually exclusive"
            )
        return self


class Tab4(FewsModel):
    tabName: str
    description: str | None = None
    timeColumnWidth: int | None = None


class ColumnAttributes(FewsModel):
    variableId: str
    columnName: str
    columnWidth: int | None = None
    attributeMapId: str | None = None
    analyse: bool | None = None
    display: bool | None = None
    userUnit: str | None = None
    multiplier: float | None = None
    divider: float | None = None
    incrementer: float | None = None


class ThresholdOverviewCrossingCountsTab(FewsModel):
    tabName: str
    thresholdGroupId: str
    relativePeriod: list[RelativeViewPeriod] = Field(min_length=1)
    countAllActiveThresholds: bool | None = None
    countWarningAreas: bool | None = None
    multipleTimeSeriesHandlingType: MultipleTimeSeriesHandlingType | None = None
    noThresholdsDefinedText: str | None = None
    noDataAvailableText: str | None = None
    crossingCountZeroText: str | None = None


class ThresholdOverviewDisplayDescriptor(FewsModel):
    """XSD choice: legacy tab1-4 branch XOR thresholdCrossingCountsTab+ branch."""

    description: str | None = None
    # legacy branch
    forecastTime: ForecastTime | None = None
    attributeNoCrossing: ThresholdOverviewAttribute | None = None
    attributeMissingValues: ThresholdOverviewAttribute | None = None
    attributeMissingForecast: ThresholdOverviewAttribute | None = None
    tab1: Tab1 | None = None
    tab2: Tab2 | None = None
    tab3: Tab3 | None = None
    tab4: Tab4 | None = None
    # new branch
    thresholdCrossingCountsTab: list[ThresholdOverviewCrossingCountsTab] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def _one_branch(self) -> ThresholdOverviewDisplayDescriptor:
        legacy = any(
            x is not None
            for x in (self.forecastTime, self.tab1, self.tab2, self.tab3)
        )
        new = bool(self.thresholdCrossingCountsTab)
        if legacy and new:
            raise ValueError(
                "displayDescriptor: legacy (tab1-4) and thresholdCrossingCountsTab "
                "branches are mutually exclusive"
            )
        if not legacy and not new:
            raise ValueError(
                "displayDescriptor: supply either the tab1-4 group or "
                "thresholdCrossingCountsTab entries"
            )
        if legacy and not all(
            x is not None for x in (self.forecastTime, self.tab1, self.tab2, self.tab3)
        ):
            raise ValueError(
                "displayDescriptor: legacy branch requires forecastTime + tab1 + "
                "tab2 + tab3 (tab4 optional; attribute* fields optional)"
            )
        return self


class ThresholdOverviewDisplay(FewsModel):
    general: ThresholdOverviewDisplayGeneral
    displayDescriptor: ThresholdOverviewDisplayDescriptor
    inputVariable: list[DataVariable] = Field(min_length=1)
    columnAttributes: list[ColumnAttributes] = Field(min_length=1)
    description: str | None = None
