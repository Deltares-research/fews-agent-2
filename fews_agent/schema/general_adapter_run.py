"""GeneralAdapterRun — root of ModelRun and Maintenance module configs.

The `<generalAdapterRun>` root element is shared between
ModuleConfigFiles/ModelRun/** and ModuleConfigFiles/Maintenance/**.
Structure:

  general                    — paths, idMaps, timezone, datum/missVal flags
  activities
    startUpActivities        — purgeActivity[]
    exportActivities         — exportStateActivity | exportDataSetActivity
                               | exportNetcdfActivity | exportRunFileActivity
    executeActivities        — executeActivity[]
    importActivities         — importStateActivity | importNetcdfActivity

Maintenance typically uses only startUpActivities + exportDataSetActivity.
ModelRun typically uses all four containers.

Modeling notes:
  - State selection is polymorphic (`<warmState>` | `<coldState>` |
    `<fromTimeSeries>`) — modeled as three optional fields on
    `StateSelection` with a validator requiring exactly one.
  - Within each activities container we keep each activity kind typed
    (PurgeActivity, ExportStateActivity, ...). FEWS has more activity
    kinds than modeled here; add them as needed.
  - `timeSeriesSets` wrapper elements reuse a small `TimeSeriesSetList`
    class so XML round-trips the wrapper faithfully.
"""
from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field, field_validator, model_validator

from .common import (
    FewsModel,
    RelativeViewPeriod,
    TimeSeriesSet,
    TimeStep,
    TimeZone,
    UnitMultiplier,
)
from .ids import IdMapId, LocationSetId, ModuleInstanceId, UnitConversionsId


# ---------------------------------------------------------------------------
# <general>
# ---------------------------------------------------------------------------

class DateTimeFormat(FewsModel):
    """Named date/time format usable in run-file `%...(id)%` substitutions
    (e.g. `%START_DATE_TIME(dateFormat)%`). `id` is an XML attribute."""

    id: str | None = None
    dateTimePattern: str


class GeneralAdapterGeneral(FewsModel):
    """`<general>` block.

    All dirs are strings because FEWS heavily uses %PLACEHOLDER% and
    $VAR$ substitution here. piVersion is optional — only some module
    families pin it.

    `missVal` is str (not float): tutorial uses "NaN" (uppercase) which
    float() accepts but str() re-emits lowercase "nan" — same precision-
    preservation trick as the other str-typed numeric fields.
    """

    rootDir: str
    workDir: str
    exportDir: str
    importDir: str
    description: str | None = None
    piVersion: str | None = None
    exportDataSetDir: str | None = None
    exportIdMap: IdMapId | None = None
    exportUnitConversionsId: UnitConversionsId | None = None
    importIdMap: IdMapId | None = None
    dumpFileDir: str | None = None
    dumpDir: str | None = None
    diagnosticFile: str | None = None
    time0Format: str | None = None
    missVal: str | None = None
    convertDatum: bool | None = None
    timeZone: TimeZone | None = None
    startDateTimeFormat: str | None = None
    endDateTimeFormat: str | None = None
    dateTimeFormat: list[DateTimeFormat] = Field(default_factory=list)
    modelTimeStep: TimeStep | None = None


# ---------------------------------------------------------------------------
# State selection (polymorphic)
# ---------------------------------------------------------------------------

class StateSearchPeriod(FewsModel):
    """Window used when hunting for a warm state to re-use."""

    unit: str
    start: int | str
    end: int | str


class WarmStateSelection(FewsModel):
    stateSearchPeriod: StateSearchPeriod


class ColdStateSelection(FewsModel):
    """Cold state reference — starts the model from a zero/reset state.

    Tutorial uses `<startDate unit="day" multiplier="0"/>` for an
    immediate-at-forecast-time cold start; other variants may carry a
    static path. Further fields can be added as encountered.
    """

    startDate: UnitMultiplier | None = None


class FromTimeSeriesSelection(FewsModel):
    """State assembled from a time series. Shape varies — left open."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class StateSelection(FewsModel):
    """Exactly one of warmState / coldState / fromTimeSeries.

    `overrulingColdStateModuleInstanceId` (optional, XSD-ordered after the
    state choice) names a cold-state fallback instance when no warm state
    is found — used by the SFINCS/HurryWave forecast+hindcast runs.
    """

    warmState: WarmStateSelection | None = None
    coldState: ColdStateSelection | None = None
    fromTimeSeries: FromTimeSeriesSelection | None = None
    overrulingColdStateModuleInstanceId: ModuleInstanceId | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> StateSelection:
        count = sum(x is not None for x in (self.warmState, self.coldState, self.fromTimeSeries))
        if count != 1:
            raise ValueError(
                "stateSelection: supply exactly one of warmState, coldState, fromTimeSeries"
            )
        return self


# ---------------------------------------------------------------------------
# startUpActivities
# ---------------------------------------------------------------------------

class PurgeActivity(FewsModel):
    """Deletes files matching a filter at module start.

    `includeSubdirectories` (optional, XSD-ordered before `filter`) makes
    the purge recurse into subfolders — used by the SFINCS/HurryWave runs.
    """

    includeSubdirectories: bool | None = None
    filter: str


class StartUpActivities(FewsModel):
    purgeActivity: list[PurgeActivity] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# exportActivities
# ---------------------------------------------------------------------------

class StateLocation(FewsModel):
    """Pair of read/write file paths for one state file."""

    readLocation: str
    writeLocation: str


class StateLocations(FewsModel):
    """`<stateLocations type="file">` wrapper around state file pairs."""

    type: str | None = None
    stateLocation: list[StateLocation] = Field(default_factory=list)


class ExportStateActivity(FewsModel):
    moduleInstanceId: ModuleInstanceId
    stateExportDir: str | None = None
    stateConfigFile: str | None = None
    stateLocations: StateLocations | None = None
    stateSelection: StateSelection | None = None


class ExportDataSetActivity(FewsModel):
    """XSD choice: export a module dataset by instance id, or deploy a named
    module dataset (`moduleDataSetName`, used by the cyclone-download run)."""

    moduleInstanceId: ModuleInstanceId | None = None
    moduleDataSetName: str | None = None
    description: str | None = None


class LocationModelLoop(FewsModel):
    """Inside `<templateLocationLooping>` — iterates a parameter file over
    every location in a locationSet for a given model."""

    locationSetId: LocationSetId
    model: str


class TemplateLocationLooping(FewsModel):
    locationModelLoop: LocationModelLoop


class ExportParameterActivity(FewsModel):
    """Renders a parameter file (e.g. `params_ubc.xml`) from a
    ModuleParameters instance, looping over locations."""

    fileName: str
    templateLocationLooping: TemplateLocationLooping
    moduleInstanceId: ModuleInstanceId


class TimeSeriesSetList(FewsModel):
    """`<timeSeriesSets>` wrapper; mirrors the XML container element."""

    timeSeriesSet: list[TimeSeriesSet] = Field(min_length=1)


class ExportNetcdfActivity(FewsModel):
    # `timeSeriesSets` may repeat: FEWS allows several <timeSeriesSets>
    # wrapper elements in one exportNetcdfActivity (e.g. Delft3D-FM wind
    # forcing exports one wrapper per parameter). Modeled as a list so a
    # single wrapper (the tutorial case) round-trips as a 1-element list.
    exportFile: str
    netcdfFormat: str | None = None
    timeSeriesSets: list[TimeSeriesSetList]
    omitMissingValues: bool | None = None

    @field_validator("timeSeriesSets", mode="before")
    @classmethod
    def _wrap_single_wrapper(cls, v: Any) -> Any:
        # Back-compat: callers (and the tutorial-era patterns) pass a single
        # <timeSeriesSets> wrapper as a dict. Wrap it so a 1-element list
        # renders byte-identically while repeated wrappers are also allowed.
        if isinstance(v, dict):
            return [v]
        return v


class RunFileStringProperty(FewsModel):
    """`<string key value>` — optional nested `<description>` (used, verbosely,
    by the cyclone-download run file). Reused for `<double>` too."""

    key: str
    value: str
    description: str | None = None


class RunFileIntProperty(FewsModel):
    key: str
    value: int


class RunFileProperties(FewsModel):
    """`<properties>` inside export*RunFileActivity — polymorphic key/value
    pairs (string + int + double)."""

    string: list[RunFileStringProperty] = Field(default_factory=list)
    int: list[RunFileIntProperty] = Field(default_factory=list)
    double: list[RunFileStringProperty] = Field(default_factory=list)


class ExportRunFileActivity(FewsModel):
    exportFile: str
    properties: RunFileProperties | None = None


class ExportNetcdfRunFileActivity(FewsModel):
    """Run-control NetCDF passed to an adapter (e.g. WesPostAdapter)."""

    description: str | None = None
    exportFile: str
    properties: RunFileProperties | None = None


class ExportCustomFormatRunFileActivity(FewsModel):
    """Renders a model run-control file from a template (e.g. SFINCS's
    `sfincs_template.inp` -> `sfincs.inp`)."""

    templateFile: str
    exportFile: str


class ExportActivities(FewsModel):
    exportStateActivity: list[ExportStateActivity] = Field(default_factory=list)
    exportDataSetActivity: list[ExportDataSetActivity] = Field(default_factory=list)
    exportParameterActivity: list[ExportParameterActivity] = Field(default_factory=list)
    exportNetcdfActivity: list[ExportNetcdfActivity] = Field(default_factory=list)
    exportRunFileActivity: list[ExportRunFileActivity] = Field(default_factory=list)
    exportNetcdfRunFileActivity: list[ExportNetcdfRunFileActivity] = Field(
        default_factory=list
    )
    exportCustomFormatRunFileActivity: list[ExportCustomFormatRunFileActivity] = Field(
        default_factory=list
    )


# ---------------------------------------------------------------------------
# executeActivities
# ---------------------------------------------------------------------------

class ExecutableCommand(FewsModel):
    """`<command>` XSD choice — either `<executable>` or the Java form
    (`<className>` + optional binDir/moduleDataSetName + optional
    customJreDir/jvmArg[]). Exactly one form must be supplied."""

    executable: str | None = None
    className: str | None = None
    binDir: str | None = None
    moduleDataSetName: str | None = None
    customJreDir: str | None = None
    jvmArg: list[str] = Field(default_factory=list)


class ExecutableArguments(FewsModel):
    """`<arguments><argument>...</argument>*</arguments>`"""

    argument: list[str] = Field(default_factory=list)


class ExecuteActivity(FewsModel):
    # Attrs
    executeOnPreviousError: bool | None = None
    # Elements in XSD sequence order
    description: str | None = None
    command: ExecutableCommand
    arguments: ExecutableArguments | None = None
    environmentVariables: dict[str, Any] | None = None
    console: dict[str, Any] | None = None
    logFile: list[dict[str, Any]] = Field(default_factory=list)
    activityDurationWeight: str | None = None
    timeOut: int | None = None
    maxNumberOfSimultaneousRuns: int | str | None = None
    waitForOtherRun: bool | None = None
    ignoreDiagnostics: bool | None = None
    ignoreExitCode: bool | None = None
    overrulingDiagnosticFile: str | None = None


class ExecuteActivities(FewsModel):
    executeActivity: list[ExecuteActivity] = Field(min_length=1)


# ---------------------------------------------------------------------------
# importActivities
# ---------------------------------------------------------------------------

class StateFileRef(FewsModel):
    """`<stateFile>` wrapper inside importStateActivity — tells FEWS where
    to copy the post-run state file to for warm-start reuse."""

    importFile: str
    relativeExportFile: str | None = None


class ImportStateActivity(FewsModel):
    """Post-run state capture for warm-start reuse.

    Two forms: the `stateFile` wrapper (Delft3D-FM/DIMR), or the
    `stateImportDir` + `stateFileDateTimePattern` form (SFINCS/HurryWave)
    where the state is a dated file matched in a directory, copied to
    `relativeExportFile` and expired after `expiryTime`.
    """

    stateConfigFile: str | None = None
    stateImportDir: str | None = None
    stateFileDateTimePattern: str | None = None
    stateFile: StateFileRef | None = None
    relativeExportFile: str | None = None
    compressedStateLocation: str | None = None
    expiryTime: UnitMultiplier | None = None
    synchLevel: int | None = None


class ImportNetcdfActivity(FewsModel):
    """XSD choice: import a single `importFile`, or scan a `folder` with a
    `fileNamePatternFilter` (used by the WES post-adapter's grid import)."""

    importFile: str | None = None
    folder: str | None = None
    fileNamePatternFilter: str | None = None
    timeSeriesSets: TimeSeriesSetList | None = None


class ImportActivities(FewsModel):
    importStateActivity: list[ImportStateActivity] = Field(default_factory=list)
    importNetcdfActivity: list[ImportNetcdfActivity] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# <activities>
# ---------------------------------------------------------------------------

class Activities(FewsModel):
    startUpActivities: StartUpActivities | None = None
    exportActivities: ExportActivities | None = None
    executeActivities: ExecuteActivities | None = None
    importActivities: ImportActivities | None = None


# ---------------------------------------------------------------------------
# root
# ---------------------------------------------------------------------------

class GeneralAdapterRun(FewsModel):
    """Root of a ModelRun or Maintenance module config."""

    general: GeneralAdapterGeneral
    activities: Activities


__all__ = [
    "GeneralAdapterRun",
    "GeneralAdapterGeneral",
    "DateTimeFormat",
    "ExportNetcdfRunFileActivity",
    "Activities",
    "StartUpActivities",
    "PurgeActivity",
    "ExportActivities",
    "ExportStateActivity",
    "ExportDataSetActivity",
    "ExportParameterActivity",
    "TemplateLocationLooping",
    "LocationModelLoop",
    "ExportNetcdfActivity",
    "ExportRunFileActivity",
    "ExportCustomFormatRunFileActivity",
    "RunFileProperties",
    "RunFileStringProperty",
    "RunFileIntProperty",
    "StateLocations",
    "StateLocation",
    "StateSelection",
    "WarmStateSelection",
    "ColdStateSelection",
    "FromTimeSeriesSelection",
    "StateSearchPeriod",
    "TimeSeriesSetList",
    "ExecuteActivities",
    "ExecuteActivity",
    "ExecutableCommand",
    "ExecutableArguments",
    "ImportActivities",
    "ImportStateActivity",
    "StateFileRef",
    "ImportNetcdfActivity",
]
