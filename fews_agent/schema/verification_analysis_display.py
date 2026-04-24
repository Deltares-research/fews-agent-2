"""VerificationAnalysisDisplay.xml — forecast-vs-flood-period verification.

The XSD ``VADColumnChoice`` group is a ``choice maxOccurs=unbounded``
over 8 named column elements (locationIdColumn, locationNameColumn,
forecastTimeColumn, forecastValueColumn, forecastLowerValueColumn,
forecastUpperValueColumn, forecastPredictionTimeColumn,
valuePropertyColumn). Modelled as parallel lists — XSD accepts any
ordering within the choice.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel, RelativeViewPeriod, TimeSeriesSet


PropertyType = Literal["string", "int", "float", "double", "boolean", "dateTime"]


class VADLocationColumn(FewsModel):
    """Simple column — ``name`` + ``width`` attributes."""

    name: str | None = None
    width: int | None = None


class ValuePropertyColumn(FewsModel):
    valuePropertyId: str
    propertyType: PropertyType | None = None
    name: str | None = None
    editable: bool | None = None
    width: int | None = None
    enumerationValue: list[str] = Field(default_factory=list)


class VADColumnChoice(FewsModel):
    """Parallel-list bag over the 8 column kinds (choice-unbounded)."""

    locationIdColumn: list[VADLocationColumn] = Field(default_factory=list)
    locationNameColumn: list[VADLocationColumn] = Field(default_factory=list)
    forecastTimeColumn: list[VADLocationColumn] = Field(default_factory=list)
    forecastValueColumn: list[VADLocationColumn] = Field(default_factory=list)
    forecastLowerValueColumn: list[VADLocationColumn] = Field(default_factory=list)
    forecastUpperValueColumn: list[VADLocationColumn] = Field(default_factory=list)
    forecastPredictionTimeColumn: list[VADLocationColumn] = Field(default_factory=list)
    valuePropertyColumn: list[ValuePropertyColumn] = Field(default_factory=list)


class ValuePropertyCountColumn(FewsModel):
    """Attribute-only element — id/value/name all required."""

    id: str
    value: str
    name: str


class ValuePropertyMaxColumn(FewsModel):
    id: str
    name: str
    value: list[str] = Field(default_factory=list)


class SelectionFilter(FewsModel):
    """Attribute-only element — all four attrs optional per XSD."""

    matchingAttributeId: str | None = None
    matchingAttributeValue: str | None = None
    selectedAttributeId: str | None = None
    filterAttributeId: str | None = None


class ConnectedTimeSeries(FewsModel):
    matchingAttributeId: str
    columns: VADColumnChoice
    connectedTimeSeriesSet: TimeSeriesSet


class VerificationAnalysisDataTab(FewsModel):
    name: str
    timeSeriesSet: TimeSeriesSet
    columns: VADColumnChoice
    filterAttributeId: str | None = None
    selectionFilter: list[SelectionFilter] = Field(default_factory=list)
    locationValuePropertyCountColumn: list[ValuePropertyCountColumn] = Field(default_factory=list)
    locationValuePropertyMaxColumn: list[ValuePropertyMaxColumn] = Field(default_factory=list)
    connectedTimeSeries: ConnectedTimeSeries | None = None
    plotTimeSeriesSet: list[TimeSeriesSet] = Field(default_factory=list)


class VerificationAnalysisDisplay(FewsModel):
    viewPeriod: RelativeViewPeriod
    dateTimeFormat: str
    floodPeriodModuleConfigFileName: str
    floodPeriodArchiveEventTypeId: str | None = None
    floodEventArchiveEventTypeId: str | None = None
    showAllFloodPeriodsTopologyNodeId: list[str] = Field(default_factory=list)
    showDataTab: list[VerificationAnalysisDataTab] = Field(default_factory=list)
