"""TimeSeriesTableDisplay.xml — multi-tab table viewer for time series."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel, TimeSeriesSet


class TimeSeriesTableForecastFilter(FewsModel):
    workflowId: list[str] = Field(min_length=1)


class TimeSeriesTableVariableDefinition(FewsModel):
    variableId: str
    timeSeriesSet: TimeSeriesSet


class TimeSeriesTableGeneral(FewsModel):
    description: str | None = None
    displayName: str
    forecastFilter: TimeSeriesTableForecastFilter | None = None
    variable: list[TimeSeriesTableVariableDefinition] = Field(default_factory=list)


class TimeSeriesTableColumn(FewsModel):
    variableId: str
    name: str | None = None


class TimeSeriesTableTab(FewsModel):
    title: str
    id: str | None = None
    showValues: bool
    showThresholdColors: bool
    locationGroupingAttributeId: str | None = None
    locationOrderingAttributeId: str | None = None
    locationLabelAttributeId: str | None = None
    thresholdGroupIdId: str | None = None
    column: list[TimeSeriesTableColumn] = Field(min_length=1)


class TimeSeriesTableDisplay(FewsModel):
    """Root of TimeSeriesTableDisplay.xml."""

    general: TimeSeriesTableGeneral
    tableTab: list[TimeSeriesTableTab] = Field(min_length=1)
