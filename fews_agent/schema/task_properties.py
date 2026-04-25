"""TaskProperties.xml — task definition used in ManualForecastDialog etc.

All 18+ top-level XSD elements are covered. Four deprecated/obsolete
branches (``archiveTask``, ``makeStateCurrent``, ``configFiles``,
``areaSelectionShapeFileBase64``) plus the complex ``stateSelection``
(~60 fields) and ``mcSystemAlerter`` sub-trees are accepted as
``dict[str, Any]`` passthroughs rendered via ``dict_to_xml``. The
commonly-authored fields are fully typed.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from .common import (
    CalendarTimeSpan,
    FewsModel,
    Period,
    TimeStep,
    UnitMultiplier,
)
from .archive_metadata import ModuleInstanceRunKey
from .mc_synchronisation import McSynchronisation
from .module_config_properties import ModuleConfigProperties


ForecastPriority = Literal["Normal", "High"]


class SingleTask(FewsModel):
    time0: str  # dateTime


class Scheduling(FewsModel):
    """Time-of-day schedule by day-of-month list + HH:mm:ss times."""

    daysOfMonth: str
    times: str
    timeZone: str | None = None


class YearlyScheduling(FewsModel):
    daysOfYear: str


class ScheduledTask(FewsModel):
    """XSD choice: schedulingInterval XOR scheduling XOR yearlyScheduling."""

    schedulingPeriod: Period
    schedulingInterval: UnitMultiplier | None = None
    scheduling: Scheduling | None = None
    yearlyScheduling: YearlyScheduling | None = None
    schedulingTime0Shift: UnitMultiplier | None = None
    cancelAllowed: bool | None = None
    suspendAllowed: bool | None = None

    @model_validator(mode="after")
    def _one_schedule(self) -> ScheduledTask:
        forms = [self.schedulingInterval, self.scheduling, self.yearlyScheduling]
        if sum(f is not None for f in forms) != 1:
            raise ValueError(
                "scheduledTask: supply exactly one of schedulingInterval / "
                "scheduling / yearlyScheduling"
            )
        return self


class TaskSelection(FewsModel):
    """XSD choice: singleTask XOR scheduledTask."""

    singleTask: SingleTask | None = None
    scheduledTask: ScheduledTask | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> TaskSelection:
        if (self.singleTask is None) == (self.scheduledTask is None):
            raise ValueError(
                "taskSelection: supply exactly one of singleTask or scheduledTask"
            )
        return self


class EnsembleMemberIndexRange(FewsModel):
    start: str  # nonNegativeIntegerStringType
    end: str | None = None


class TaskProperties(FewsModel):
    """Minimal-useful TaskProperties. See module docstring for omitted
    elements."""

    workflowId: str
    taskSelection: TaskSelection
    description: str | None = None
    userId: str | None = None
    forecastPriority: ForecastPriority = "Normal"
    forecastLength: UnitMultiplier | None = None
    makeForcastCurrent: bool | None = None
    whatIfScenarioId: str | None = None
    # stateSelection: dict passthrough (XSD StateSelectionComplexType ~60
    # fields). Alias ``stateSelectionXml`` retained for legacy callers
    # that pre-render an XML string.
    stateSelection: dict[str, Any] | None = None
    stateSelectionXml: str | None = None
    # areaSelectionShapeFileBase64: base-64 .shp blob passthrough
    areaSelectionShapeFileBase64: str | None = None
    selectedLocationId: list[str] = Field(default_factory=list)
    # makeStateCurrent: deprecated (not used since 2017.02) but XSD-valid
    makeStateCurrent: bool | None = None
    runExpiryTime: CalendarTimeSpan | None = None
    # configFiles: OBSOLETE tree (ConfigFilesComplexType) — dict passthrough
    configFiles: dict[str, Any] | None = None
    # archiveTask: deprecated (old archive) — dict passthrough
    archiveTask: dict[str, Any] | None = None
    taskRunType: str | None = None
    properties: ModuleConfigProperties | None = None
    activeModuleInstanceRuns: list[ModuleInstanceRunKey] = Field(default_factory=list)
    mcSynchronisation: McSynchronisation | None = None
    # mcSystemAlerter: big hyphenated-element tree — dict passthrough
    mcSystemAlerter: dict[str, Any] | None = None
    ensembleParts: int | None = None
    ensembleMemberIndexRange: list[EnsembleMemberIndexRange] = Field(default_factory=list)
    moduleInstanceIndices: list[int] = Field(default_factory=list)


class TaskListTaskGroup(FewsModel):
    """Fields of the <task> element in taskList.xml — wraps TaskProperties
    plus surrounding task-status metadata."""

    taskStatus: Literal["P", "S", "D"]
    runOnFailOver: bool
    taskProperties: TaskProperties
    taskTag: str | None = None
    suspendDutyInFailOver: bool | None = None
    runOption: Literal["all", "allOneAtATime", "allMostRecentOnly"] | None = None


class TaskList(FewsModel):
    """Root of TaskList.xml — optional list of scheduled tasks."""

    task: list[TaskListTaskGroup] = Field(default_factory=list)
