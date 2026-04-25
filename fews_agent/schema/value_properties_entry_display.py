"""ValuePropertiesEntryDisplay.xml — display config for entering and
editing value properties on time series.

The XSD has a top-level sequence with a wide mix of optional fields
followed by a final ``valueProperty`` / ``newLine`` choice (1+ items)
and optional sub/forecast tables. The deeply-nested column choice in
``subLocationsTable`` and the input/forecast structures are passed
through as dicts to keep this schema tractable while still preserving
top-level XSD-sequence ordering.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .common import FewsModel


class VariableDef(FewsModel):
    """XSD VariableDefinitionValuePropertiesEntryDisplayComplexType.

    A simple {variableId, timeSeriesSet} pair. ``timeSeriesSet`` is
    passed through as a dict to avoid duplicating the broad common.py
    TimeSeriesSet shape here; templates emit it via ``dict_to_xml``.
    """

    variableId: str
    timeSeriesSet: dict[str, Any] = Field(default_factory=dict)


class ExportButton(FewsModel):
    """XSD ExportButtonComplexType — a button on the entry display."""

    icon: str | None = None
    type: Literal[
        "initial",
        "update",
        "correct",
        "stopSequence",
        "runWorkflow",
        "reportDraft",
        "reportFinal",
    ]
    templateFile: str | None = None
    defaultFolder: str | None = None
    defaultFileName: str | None = None
    openFileAfterCreation: bool | None = None
    workflowId: str | None = None
    confirmationQuestion: str | None = None
    name: str | None = None


class SubLocationsStructure(FewsModel):
    """XSD SubLocationsStructureComplexType (from sharedTypes)."""

    variableId: str
    matchingSubLocationAttributeId: str
    connectedSubLocationsStructureId: str | None = None
    connectedSubLocationIdFunction: str | None = None
    forecastLocationsStructureId: str | None = None
    forecastLocationIdFunction: str | None = None
    externalForecastLocationIdFunction: str | None = None
    observationVariableId: str | None = None
    observationTendencyVariableId: str | None = None
    observationPeakVariableId: str | None = None
    observationLocationIdFunction: str | None = None
    externalObservationLocationIdFunction: str | None = None
    draftTemplateFile: str | None = None
    templateFile: str | None = None
    id: str | None = None


class ForecastLocationsStructure(FewsModel):
    """XSD ForecastLocationsStructureComplexType (from sharedTypes)."""

    variableId: str
    datumAttributeFunction: str | None = None
    locationTypeAttributeFunction: str | None = None
    minorSeverityAttributeFunction: str | None = None
    moderateSeverityAttributeFunction: str | None = None
    majorSeverityAttributeFunction: str | None = None
    id: str | None = None
    convertDatum: bool | None = None


class DateFormat(FewsModel):
    """XSD ValuePropertiesEntryDisplayDateFormatComplexType."""

    timeZone: dict[str, Any] | None = None  # TimeZoneComplexType
    timeZoneNameLocationAttributeId: str | None = None
    dateTimePattern: str
    id: str


class NumberFormat(FewsModel):
    """XSD ValuePropertiesEntryDisplayNumberFormatComplexType."""

    pattern: str
    id: str


class EnumerationValue(FewsModel):
    """XSD ValuePropertiesEntryDisplayEnumerationValueComplexType.

    Both attributes are required.
    """

    code: str
    label: str


class SpecialEntryValueProperty(FewsModel):
    """XSD SpecialEntryValuePropertyComplexType."""

    variableId: str | None = None
    valueType: str | None = None
    type: str | None = None  # specialValuePropertyTypeEnumStringType


class ValueProperty(FewsModel):
    """XSD EntryValuePropertyComplexType.

    Modelled with all its option attrs, plus a flat optional default
    for the choice element (defaultValue / defaultValueAttributeFunction
    / templateValueAttributeFunction). The template re-emits attrs in
    XSD order.
    """

    enumerationValue: list[EnumerationValue] = Field(default_factory=list)
    defaultValue: str | None = None
    defaultValueAttributeFunction: str | None = None
    templateValueAttributeFunction: str | None = None
    special: SpecialEntryValueProperty | None = None
    # attrs
    id: str
    propertyType: str
    name: str | None = None
    enabled: bool | None = None
    numberOfLines: int | None = None
    width: int | None = None
    forceUpperCase: bool | None = None
    formatId: str | None = None
    convertDatum: bool | None = None


class ValuePropertyOrNewLine(FewsModel):
    """One element in the property/newLine ordered choice — exactly one
    of ``valueProperty`` (full payload) or ``newLine`` (empty marker).
    """

    valueProperty: ValueProperty | None = None
    newLine: bool | None = None  # truthy means emit <newLine/>


class SubLocationsTable(FewsModel):
    """XSD SubLocationsTableComplexType.

    The unbounded column choice is heterogeneous (8 column variants) so
    the full column list is passed through as a single ``columns`` list
    of single-key dicts; ``dict_to_xml`` will emit each in order.
    """

    title: str | None = None
    maxVisibleRows: int | None = None
    subLocationsStructureId: str | None = None
    columns: list[dict[str, Any]] = Field(default_factory=list)
    id: str


class ForecastCreationTableColumn(FewsModel):
    """XSD ForecastCreationTableColumnComplexType."""

    enumerationValue: list[str] = Field(default_factory=list)
    id: str
    name: str
    width: int
    type: str  # forecastCreationTableEnumStringType


class ForecastCreationPanel(FewsModel):
    """XSD ForecastCreationPanelComplexType."""

    title: str | None = None
    forecastLocationsVariableId: str
    valuePropertyOrNewLine: list[ValuePropertyOrNewLine] = Field(default_factory=list)
    forecastCreationTable: dict[str, Any] = Field(default_factory=dict)


class ValuePropertiesEntryDisplay(FewsModel):
    """Root of ValuePropertiesEntryDisplay.xml."""

    variable: list[VariableDef] = Field(default_factory=list)
    enableButtonsByPhase: bool | None = None
    button: list[ExportButton] = Field(default_factory=list)
    valuePropertiesVariableId: str
    externalIdAttributeFunction: str | None = None
    externalNameAttributeFunction: str | None = None
    timeZoneAttributeFunction: str | None = None
    convertDatumAttributeFunction: str | None = None
    subLocationsStructure: list[SubLocationsStructure] = Field(default_factory=list)
    forecastLocationsStructure: ForecastLocationsStructure | None = None
    dateFormat: list[DateFormat] = Field(default_factory=list)
    numberFormat: list[NumberFormat] = Field(default_factory=list)
    valuePropertyOrNewLine: list[ValuePropertyOrNewLine] = Field(min_length=1)
    subLocationsTable: list[SubLocationsTable] = Field(default_factory=list, max_length=2)
    forecastCreationPanel: ForecastCreationPanel | None = None
