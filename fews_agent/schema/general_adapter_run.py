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

from pydantic import ConfigDict, Field, model_validator

from .common import FewsModel, RelativeViewPeriod, TimeSeriesSet, TimeZone
from .ids import IdMapId, ModuleInstanceId


# ---------------------------------------------------------------------------
# <general>
# ---------------------------------------------------------------------------

class GeneralAdapterGeneral(FewsModel):
    """`<general>` block.

    All dirs are strings because FEWS heavily uses %PLACEHOLDER% and
    $VAR$ substitution here. piVersion is optional — only some module
    families pin it.
    """

    rootDir: str
    workDir: str
    exportDir: str
    importDir: str
    piVersion: str | None = None
    exportDataSetDir: str | None = None
    exportIdMap: IdMapId | None = None
    importIdMap: IdMapId | None = None
    dumpFileDir: str | None = None
    dumpDir: str | None = None
    diagnosticFile: str | None = None
    time0Format: str | None = None
    missVal: float | None = None
    convertDatum: bool | None = None
    timeZone: TimeZone | None = None


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
    """Cold state reference. Typically a path; other fields may appear."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class FromTimeSeriesSelection(FewsModel):
    """State assembled from a time series. Shape varies — left open."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class StateSelection(FewsModel):
    """Exactly one of warmState / coldState / fromTimeSeries."""

    warmState: WarmStateSelection | None = None
    coldState: ColdStateSelection | None = None
    fromTimeSeries: FromTimeSeriesSelection | None = None

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
    """Deletes files matching a filter at module start."""

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
    moduleInstanceId: ModuleInstanceId
    description: str | None = None


class TimeSeriesSetList(FewsModel):
    """`<timeSeriesSets>` wrapper; mirrors the XML container element."""

    timeSeriesSet: list[TimeSeriesSet] = Field(min_length=1)


class ExportNetcdfActivity(FewsModel):
    exportFile: str
    timeSeriesSets: TimeSeriesSetList


class ExportRunFileActivity(FewsModel):
    exportFile: str


class ExportActivities(FewsModel):
    exportStateActivity: list[ExportStateActivity] = Field(default_factory=list)
    exportDataSetActivity: list[ExportDataSetActivity] = Field(default_factory=list)
    exportNetcdfActivity: list[ExportNetcdfActivity] = Field(default_factory=list)
    exportRunFileActivity: list[ExportRunFileActivity] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# executeActivities
# ---------------------------------------------------------------------------

class ExecutableCommand(FewsModel):
    """`<command><executable>...</executable></command>`"""

    executable: str


class ExecutableArguments(FewsModel):
    """`<arguments><argument>...</argument>*</arguments>`"""

    argument: list[str] = Field(default_factory=list)


class ExecuteActivity(FewsModel):
    command: ExecutableCommand
    description: str | None = None
    arguments: ExecutableArguments | None = None
    timeOut: int | None = None
    ignoreDiagnostics: bool | None = None
    overrulingDiagnosticFile: str | None = None


class ExecuteActivities(FewsModel):
    executeActivity: list[ExecuteActivity] = Field(min_length=1)


# ---------------------------------------------------------------------------
# importActivities
# ---------------------------------------------------------------------------

class ImportStateActivity(FewsModel):
    stateConfigFile: str


class ImportNetcdfActivity(FewsModel):
    importFile: str
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
    "Activities",
    "StartUpActivities",
    "PurgeActivity",
    "ExportActivities",
    "ExportStateActivity",
    "ExportDataSetActivity",
    "ExportNetcdfActivity",
    "ExportRunFileActivity",
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
    "ImportNetcdfActivity",
]
