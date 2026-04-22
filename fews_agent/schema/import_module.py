"""ImportModule — `<timeSeriesImportRun>` module config.

One file contains one or more `<import>` blocks. Each block pulls from one
source (URL or folder) and writes into one or more `<timeSeriesSet>`s.

Notable points:
  - `ImportViewPeriod` is a variant of `RelativeViewPeriod` — its `start`
    and `end` are strings, since imports heavily use FEWS runtime
    placeholders like `$STARTTIME$` / `$ENDTIME$` that would not parse
    as int. It also carries the `startOverrulable` / `endOverrulable`
    attributes that only appear in import contexts.
  - `ImportProperties` holds `<string>` and `<bool>` key-value entries.
    Other property types (`int`, `double`, `dateTime`) can be added as
    they're encountered.
  - `TimeSeriesImportRun` aliases its `import_` field to the XML element
    name `import` (a Python keyword). Thanks to
    `populate_by_name=True` on the base, input JSON can use either key.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from pydantic import Field

from .common import (
    ExternUnit,
    FewsModel,
    RelativeViewPeriod,
    TimeSeriesSet,
    TimeStep,
    TimeZone,
)
from .ids import IdMapId, ParameterId, UnitConversionsId


class StartTimeShift(FewsModel):
    """Shifts the effective start time for one parameter on import.

    `<relativePeriod>` here is the same XSD shape as `<relativeViewPeriod>`
    elsewhere — just a different element name. We reuse RelativeViewPeriod.
    """

    parameterId: ParameterId
    relativePeriod: RelativeViewPeriod


class StringProperty(FewsModel):
    """`<string key="..." value="..."/>`"""

    key: str
    value: str


class BoolProperty(FewsModel):
    """`<bool key="..." value="true|false"/>`"""

    key: str
    value: bool


class ImportProperties(FewsModel):
    """Polymorphic properties container.

    XML emits one element per entry with the tag matching the property
    type: `<string>`, `<bool>`, etc.
    """

    string: list[StringProperty] = Field(default_factory=list)
    bool: list[BoolProperty] = Field(default_factory=list)


class FileNameDateTimeFilter(FewsModel):
    """Parses a date/time out of a filename segment at the given subfolder
    level. Used by EarthObservation and Snow imports to align filenames
    with FEWS timestamps during auto-ingest.
    """

    subFolderLevel: int  # XML attribute
    timeStep: TimeStep
    dateTimePattern: str
    preFixLength: int
    postFixLength: int


class LocationColumn(FewsModel):
    """CSV `<locationColumn name="..."/>` — names the column carrying station ids."""

    name: str


class DateTimeColumn(FewsModel):
    """CSV `<dateTimeColumn name="..." pattern="..."/>`."""

    name: str
    pattern: str


class ValueColumn(FewsModel):
    """CSV `<valueColumn name="..." unit="..." parameterId="..."/>`."""

    name: str
    unit: str
    parameterId: ParameterId


class CsvTable(FewsModel):
    """`<table>` block for generalCSV imports."""

    locationColumn: LocationColumn
    dateTimeColumn: DateTimeColumn
    valueColumn: list[ValueColumn] = Field(min_length=1)


class Tolerance(FewsModel):
    """Import-level tolerance: maximum deviation between expected sample
    time and the value actually observed. XML: `<tolerance timeUnit="..."
    unitCount="..." parameterId="..."/>` (all attributes)."""

    timeUnit: str
    unitCount: int
    parameterId: ParameterId


class ImportGeneral(FewsModel):
    """The `<general>` block inside an `<import>`.

    Invariant: at least one of `serverUrl` or `folder` is supplied.
    """

    importType: str
    idMapId: IdMapId
    serverUrl: str | None = None
    folder: str | None = None
    user: str | None = None
    password: str | None = None
    table: CsvTable | None = None
    fileNameDateTimeFilter: list[FileNameDateTimeFilter] = Field(default_factory=list)
    fileNamePatternFilter: str | None = None
    fileNameObservationDateTimePattern: str | None = None
    failedFolder: str | None = None
    backupFolder: str | None = None
    relativeViewPeriod: RelativeViewPeriod | None = None
    unitConversionsId: UnitConversionsId | None = None
    # str (not float) preserves scientific literals like "-3.402823E38"
    # which Python floats emit as "-3.402823e+38" and break C14N match.
    missingValue: str | None = None
    importTimeZone: TimeZone | None = None
    dataFeedId: str | None = None
    expiryTime: TimeStep | None = None
    skipFirstLinesCount: int | None = None

    @model_validator(mode="after")
    def _has_source(self) -> ImportGeneral:
        if self.serverUrl is None and self.folder is None:
            raise ValueError(
                "import.general: supply at least one of serverUrl or folder"
            )
        return self


class ImportBlock(FewsModel):
    """One `<import>` block — one source, one or more output timeSeriesSets."""

    general: ImportGeneral
    timeSeriesSet: list[TimeSeriesSet] = Field(min_length=1)
    startTimeShift: StartTimeShift | None = None
    properties: ImportProperties | None = None
    tolerance: list[Tolerance] = Field(default_factory=list)
    externUnit: list[ExternUnit] = Field(default_factory=list)


class TimeSeriesImportRun(FewsModel):
    """Root of ModuleConfigFiles/Import/**/<X>.xml.

    `import_` is aliased to the XML element name `import` (a Python
    keyword). Input accepts either key because of populate_by_name.
    """

    import_: list[ImportBlock] = Field(min_length=1, alias="import")
