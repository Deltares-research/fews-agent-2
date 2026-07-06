"""ImportModule — `<timeSeriesImportRun>` module config.

One file contains one or more `<import>` blocks. Each block pulls from one
source (folder / JDBC / server URL) and writes into one or more
`<timeSeriesSet>`s.

The XSD surface is very large (one `<general>` block with ~70 optional
fields, a free-choice CSV `<table>` of ~28 column kinds, OAuth2/FTP/JDBC
transport options, typed properties, forecast-search and filename-pattern
options). All of it is modelled here as optional fields; the common case
(grid imports: importType + idMapId + serverUrl/folder + a timeSeriesSet)
renders unchanged. Where the XSD uses a `<choice>`, the model is a
permissive superset and XSD validation is the loud gate (per the repo's
"validate twice" principle).

Notable points:
  - `ImportProperties` holds typed key/value entries (`string`, `int`,
    `float`, `double`, `bool`, `dateTime`).
  - `TimeSeriesImportRun` aliases its `import_` field to the XML element
    name `import` (a Python keyword); `populate_by_name=True` on the base
    lets input JSON use either key.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from .common import (
    ExternUnit,
    FewsModel,
    RelativePeriod,
    RelativeTime,
    RelativeViewPeriod,
    TimeSeriesSet,
    TimeStep,
    TimeZone,
    UnitMultiplier,
)
from .ids import IdMapId, ParameterId, UnitConversionsId


def _as_list(v: Any) -> Any:
    if isinstance(v, dict):
        return [v]
    return v


class StartTimeShift(FewsModel):
    """Shifts the effective start time for one parameter on import.

    `<relativePeriod>` here is the same XSD shape as `<relativeViewPeriod>`
    elsewhere — just a different element name. We reuse RelativeViewPeriod.
    """

    parameterId: ParameterId
    relativePeriod: RelativeViewPeriod
    locationId: str | None = None
    locationSetId: str | None = None


# --- properties --------------------------------------------------------

class StringProperty(FewsModel):
    """`<string key="..." value="..."/>` (also reused for int/float/double —
    same key+value shape; value kept as str to preserve placeholders)."""

    key: str
    value: str


class BoolProperty(FewsModel):
    """`<bool key="..." value="true|false"/>`"""

    key: str
    value: bool


class ImportDateTimeProperty(FewsModel):
    """`<dateTime key="..." date="..." time="..."/>`"""

    key: str
    date: str
    time: str


class ImportProperties(FewsModel):
    """Polymorphic properties container — one element per entry, tag matching
    the property type."""

    description: str | None = None
    string: list[StringProperty] = Field(default_factory=list)
    int: list[StringProperty] = Field(default_factory=list)
    float: list[StringProperty] = Field(default_factory=list)
    double: list[StringProperty] = Field(default_factory=list)
    bool: list[BoolProperty] = Field(default_factory=list)
    dateTime: list[ImportDateTimeProperty] = Field(default_factory=list)


class FileNameDateTimeFilter(FewsModel):
    """Parses a date/time out of a filename segment at the given subfolder
    level."""

    subFolderLevel: int  # XML attribute
    timeStep: TimeStep
    dateTimePattern: str
    preFixLength: int
    postFixLength: int


# --- CSV table columns -------------------------------------------------

class Column(FewsModel):
    """Plain `ColumnComplexType` — `name` attribute only. Base for the
    column kinds that carry no extra attributes."""

    name: str | None = None


class LocationColumn(Column):
    """CSV `<locationColumn name="..."/>`."""


class DateTimeColumn(Column):
    """`<dateTimeColumn name="..." pattern="..."/>` (also date/time/forecast
    date-time columns share this shape)."""

    pattern: str | None = None


class ValueColumn(Column):
    """`<valueColumn name="..." unit="..." parameterId="..."/>` plus the full
    optional attribute set (parser, locationId, ensembleMemberIndex, time,
    dayOfMonth, enumeration/numerical gates)."""

    unit: str | None = None
    parameterId: ParameterId | None = None
    parser: str | None = None
    locationId: str | None = None
    ensembleMemberIndex: int | None = None
    time: str | None = None
    dayOfMonth: int | None = None
    ignoreForEnumerationParameters: bool | None = None
    requireEnumerationParameters: bool | None = None
    ignoreForNumericalParameters: bool | None = None
    requireNumericalParameters: bool | None = None


class FlagColumn(Column):
    locationId: str | None = None
    parameterId: str | None = None


class CsvFlagSourceColumn(Column):
    id: str | None = None


class QualifierColumn(Column):
    prefix: str | None = None
    defaultValue: str | None = None


class SampleIdColumn(Column):
    prefix: str | None = None


class PropertyColumn(Column):
    key: str
    pattern: str | None = None


class AttributeColumn(Column):
    id: str
    pattern: str | None = None


class CsvTable(FewsModel):
    """`<table>` for generalCsv / database imports. The XSD is a free
    `<choice maxOccurs="unbounded">` of column kinds; modelled here as one
    optional (list-)field per kind. The common case (locationColumn +
    dateTimeColumn + valueColumn[]) renders unchanged."""

    name: str | None = None
    # Ordered escape hatch: when non-empty, columns render in THIS order
    # (each dict carries `kind` = the element tag + its attrs), bypassing the
    # per-type grouping below. Required for positional CSV parses where
    # value/skipped columns interleave (e.g. NDBC) — the grouped path would
    # reorder them and misalign the parse.
    columns: list[dict[str, Any]] = Field(default_factory=list)
    # Common case (kept single for back-compat with existing patterns).
    locationColumn: LocationColumn | None = None
    dateTimeColumn: DateTimeColumn | None = None
    valueColumn: list[ValueColumn] = Field(default_factory=list)
    # Full column set (each repeatable per the XSD choice).
    dateColumn: list[DateTimeColumn] = Field(default_factory=list)
    yearColumn: list[Column] = Field(default_factory=list)
    monthColumn: list[Column] = Field(default_factory=list)
    dayColumn: list[Column] = Field(default_factory=list)
    timeColumn: list[DateTimeColumn] = Field(default_factory=list)
    hourColumn: list[Column] = Field(default_factory=list)
    minuteColumn: list[Column] = Field(default_factory=list)
    secondColumn: list[Column] = Field(default_factory=list)
    forecastDateTimeColumn: list[DateTimeColumn] = Field(default_factory=list)
    forecastDateColumn: list[DateTimeColumn] = Field(default_factory=list)
    forecastTimeColumn: list[DateTimeColumn] = Field(default_factory=list)
    startDateTimeColumn: list[DateTimeColumn] = Field(default_factory=list)
    endDateTimeColumn: list[DateTimeColumn] = Field(default_factory=list)
    parameterColumn: list[Column] = Field(default_factory=list)
    qualifierColumn: list[QualifierColumn] = Field(default_factory=list)
    ensembleColumn: list[Column] = Field(default_factory=list)
    ensembleMemberColumn: list[Column] = Field(default_factory=list)
    commentColumn: list[Column] = Field(default_factory=list)
    userColumn: list[Column] = Field(default_factory=list)
    flagColumn: list[FlagColumn] = Field(default_factory=list)
    flagSourceColumn: list[CsvFlagSourceColumn] = Field(default_factory=list)
    unitColumn: list[Column] = Field(default_factory=list)
    skippedColumn: list[Column] = Field(default_factory=list)
    sampleIdColumn: list[SampleIdColumn] = Field(default_factory=list)
    propertyColumn: list[PropertyColumn] = Field(default_factory=list)
    attributeColumn: list[AttributeColumn] = Field(default_factory=list)
    limitSymbolColumn: list[Column] = Field(default_factory=list)
    lineNumberColumn: list[Column] = Field(default_factory=list)


class Tolerance(FewsModel):
    """Import-level tolerance (all attributes)."""

    timeUnit: str
    unitCount: int
    parameterId: ParameterId


class Comment(FewsModel):
    """`<comment>` — text attached to imported values, with placeholder
    substitution for import/file date-times."""

    dateTimePattern: str | None = None
    timeZone: TimeZone | None = None
    commentForFirstValue: str | None = None
    commentForAllValues: str | None = None


class OAuth2Config(FewsModel):
    """OAuth2 token-endpoint config for protected server imports."""

    authUrl: str
    clientId: str | None = None
    clientSecret: str | None = None
    scope: list[str] = Field(default_factory=list)
    audience: list[str] = Field(default_factory=list)
    issuer: str | None = None
    refreshToken: str | None = None


class CommentIgnoreFilter(FewsModel):
    """`<commentIgnoreFilter>` — XSD choice of a single ignore-pattern regex
    or a list of exact comments to ignore."""

    ignoreCommentPattern: str | None = None
    ignoreComment: list[str] = Field(default_factory=list)


class GroupImportPattern(FewsModel):
    """A complete-forecast file-group: import once `numberOfFiles` matching
    `fileNameDateTimePattern` are present, else fail after `waitingTime`."""

    numberOfFiles: int
    fileNameDateTimePattern: str
    waitingTime: UnitMultiplier


class ImportGeneral(FewsModel):
    """The `<general>` block inside an `<import>`.

    Invariant: at least one source (`serverUrl` / `folder` / `jdbcConnectionString`)
    is supplied. Fields follow the XSD sequence order.
    """

    description: str | None = None
    # importType choice: importTypeStandard | importType | (parserClassName + ...)
    importTypeStandard: str | None = None
    importType: str | None = None
    parserClassName: str | None = None
    binDir: str | None = None
    moduleDataSetName: str | None = None
    # source choice: folder-seq | jdbc-seq | server-seq
    folder: str | None = None
    fileNameDateTimeFilter: list[FileNameDateTimeFilter] = Field(default_factory=list)
    fileNamePatternFilter: str | None = None
    fileNameEnsembleMemberIndexPattern: str | None = None
    fileNameObservationDateTimePattern: str | None = None
    fileNameForecastCreationDateTimePattern: str | None = None
    fileNamePrefixForecastCreationDateTimePattern: str | None = None
    fileNamePostfixForecastCreationDateTimePattern: str | None = None
    fileNameForecastCreationDateTimePatternFromZip: str | None = None
    fileNameLocationIdPattern: str | None = None
    fileNameParameterIdPattern: str | None = None
    maxAllowedFolderSizeMB: int | None = None
    failedFolder: str | None = None
    backupFolder: str | None = None
    suspendedFolder: str | None = None
    importTriggeringFile: list[str] = Field(default_factory=list)
    groupImportPattern: GroupImportPattern | None = None
    deleteImportedFiles: bool | None = None
    # FtpOptionsGroup
    ftpPassiveMode: bool | None = None
    sftpPrivateKeyFile: str | None = None
    sftpPrivateKey: str | None = None
    sftpHostKeyFile: str | None = None
    sftpPassPhraseFile: str | None = None
    sftpPassPhrase: str | None = None
    # jdbc-seq
    jdbcDriverClass: str | None = None
    jdbcBinDir: str | None = None
    jdbcConnectionString: str | None = None
    jdbcConnectionTimeOutMillis: int | None = None
    # server-seq
    serverUrl: str | None = None
    backupServerUrl: list[str] = Field(default_factory=list)
    downLoadFolder: str | None = None
    connectionTimeOutMillis: int | None = None
    # auth
    user: str | None = None
    encryptedPassword: str | None = None
    password: str | None = None
    oauth2Config: OAuth2Config | None = None
    # period choice: WantedPeriod (relativeViewPeriod | startDateTime+endDateTime)
    #                + onlyGaps  |  forecastSearchPeriod
    #                |  externalForecastTimesSearchRelativePeriod + ...CardinalTimeStep
    relativeViewPeriod: RelativeViewPeriod | None = None
    startDateTime: str | None = None
    endDateTime: str | None = None
    onlyGaps: bool | None = None
    forecastSearchPeriod: RelativePeriod | None = None
    externalForecastTimesSearchRelativePeriod: RelativePeriod | None = None
    externalForecastTimesCardinalTimeStep: TimeStep | None = None
    forecastMaxAge: UnitMultiplier | None = None
    table: list[CsvTable] = Field(default_factory=list)
    validate_: bool | None = Field(default=None, alias="validate")
    logErrorsAsWarnings: bool | None = None
    logErrorsAsWarningsToFileOnly: bool | None = None
    logWarningsForUnmappableTimeSeries: bool | None = None
    failOnUnmappableTimeSeries: bool | None = None
    logWarningsForUnmappableLocations: bool | None = None
    logWarningsForUnmappableParameters: bool | None = None
    logWarningsForUnmappableQualifiers: bool | None = None
    failOnUnmappableLocations: bool | None = None
    maxLogWarnings: int | None = None
    logWarningsToSeparateFile: bool | None = None
    ignoreFileNotFoundWarnings: bool | None = None
    idMapId: IdMapId | None = None
    moduleInstanceAware: bool | None = None
    useStandardName: bool | None = None
    maximumSnapDistance: str | None = None
    maximumVerticalSnapDistance: str | None = None
    mapLocationsByLayerSigmaCoordinate: bool | None = None
    unitConversionsId: UnitConversionsId | None = None
    disableImportOnMissingUnitConversion: bool | None = None
    flagConversionsId: str | None = None
    flagSourceConversionsId: str | None = None
    # str (not float) preserves scientific literals like "-3.402823E38".
    missingValue: str | None = None
    missingValueText: list[str] = Field(default_factory=list)
    traceValue: list[str] = Field(default_factory=list)
    importTimeZone: TimeZone | None = None
    gridStartPoint: str | None = None
    geoDatum: str | None = None
    importTypeConfig: str | None = None
    dataFeedId: str | None = None
    disableDataFeedInfo: bool | None = None
    convertDatum: bool | None = None
    skipMissingValues: bool | None = None
    skipEmptyTextValues: bool | None = None
    ignoreNonExistingLocationSets: bool | None = None
    reportChangedValues: bool | None = None
    actionLogEventTypeId: str | None = None
    comment: Comment | None = None
    synchLevel: int | None = None
    expiryTime: TimeStep | None = None
    relativeForecastTime: RelativeTime | None = None
    skipFirstLinesCount: int | None = None
    gotoLineWhichStartsWith: str | None = None
    commentIgnoreFilter: CommentIgnoreFilter | None = None
    ignoreEmptyComments: bool | None = None
    mergeWithExistingSampleData: bool | None = None
    rejectCompleteSampleOnUnmappableId: bool | None = None
    rejectCompleteSampleOnDuplicateValues: bool | None = None
    overwriteAnnotations: bool | None = None
    trimPeriodWhenLastImportedTimeStepAfterPeriod: bool | None = None
    columnSeparator: str | None = None
    decimalSeparator: str | None = None
    dateTimePattern: str | None = None
    charset: str | None = None

    @field_validator("table", mode="before")
    @classmethod
    def _wrap_table(cls, v: Any) -> Any:
        return _as_list(v)

    @model_validator(mode="after")
    def _has_source(self) -> ImportGeneral:
        if (
            self.serverUrl is None
            and self.folder is None
            and self.jdbcConnectionString is None
        ):
            raise ValueError(
                "import.general: supply at least one of serverUrl, folder, "
                "or jdbcConnectionString"
            )
        return self


class GribRecordTimeIgnore(FewsModel):
    """Deprecated `<gribRecordTimeIgnore>` — attribute-only."""

    locationId: str
    parameterId: str
    ignore: bool


class InterpolateSerie(FewsModel):
    """`<interpolateSerie parameterId="..." interpolate="..."/>`."""

    parameterId: str
    interpolate: bool


class ImportBlock(FewsModel):
    """One `<import>` block — one source, one or more output timeSeriesSets."""

    general: ImportGeneral
    tolerance: list[Tolerance] = Field(default_factory=list)
    startTimeShift: list[StartTimeShift] = Field(default_factory=list)
    properties: ImportProperties | None = None
    # output choice: timeSeriesSet[] | temporary | locationId[] | locationSetId
    #                | annotationLocationSetId
    timeSeriesSet: list[TimeSeriesSet] = Field(default_factory=list)
    temporary: bool | None = None
    locationId: list[str] = Field(default_factory=list)
    locationSetId: str | None = None
    annotationLocationSetId: str | None = None
    externUnit: list[ExternUnit] = Field(default_factory=list)
    gribRecordTimeIgnore: list[GribRecordTimeIgnore] = Field(default_factory=list)
    interpolateSerie: list[InterpolateSerie] = Field(default_factory=list)
    minimumAgeForImport: UnitMultiplier | None = None

    @field_validator("startTimeShift", "timeSeriesSet", mode="before")
    @classmethod
    def _wrap(cls, v: Any) -> Any:
        return _as_list(v)


class TimeSeriesImportRun(FewsModel):
    """Root of ModuleConfigFiles/Import/**/<X>.xml.

    `import_` is aliased to the XML element name `import` (a Python
    keyword). Input accepts either key because of populate_by_name.
    """

    import_: list[ImportBlock] = Field(min_length=1, alias="import")
