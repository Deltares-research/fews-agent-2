"""ArchiveMetaData.xml — bookkeeping for a single task run.

Records all (warm)states, time-series blobs, module-instance runs,
modifier descriptors and derived task-runs used during one task run,
plus FSS latest-data timestamps and version stamps.

Many of the wrapper elements are optional lists whose XSDs are
anonymous inline complexTypes (usedStates / usedTimeSeriesBlobs /
usedTaskRuns / usedTasks / usedModuleInstanceRuns / usedFewsSessions /
usedWhatIfScenarios / usedModifierDescriptors). Each wraps a single
list of Key-type items — we model them directly as optional lists on
``ArchiveMetaData`` and let the template emit the wrappers.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel, Period


class DateTimePair(FewsModel):
    """XSD DateTimeComplexType — ``date`` required, ``time`` optional."""

    date: str
    time: str | None = None


class WarmStateKey(FewsModel):
    taskRunId: str
    stateId: list[str] = Field(min_length=1)


class TimeSeriesBlobKey(FewsModel):
    locationId: str
    parameterId: str
    period: Period


class TaskRunKey(FewsModel):
    taskRunId: str


class TaskKey(FewsModel):
    taskId: str


class ModuleInstanceRunKey(FewsModel):
    taskRunId: str
    moduleInstanceId: list[str] = Field(min_length=1)


class FewsSessionKey(FewsModel):
    taskRunId: str


class WhatIfScenarioKey(FewsModel):
    whatIfId: str


class ModifierDescriptorKey(FewsModel):
    modifierId: int
    taskRunId: str


class LatestAvailableData(FewsModel):
    """`<latestAvailableData name="...">`. Name is the FSS identifier."""

    name: str
    latestAvailableTime: DateTimePair


# Wrapper elements: each `<used*>` wraps a single list of inner items whose
# element name differs from the wrapper. Modeled as one-field wrappers so the
# inner element name round-trips faithfully (parse → render).

class UsedStates(FewsModel):
    warmState: list[WarmStateKey] = Field(min_length=1)


class UsedTimeSeriesBlobs(FewsModel):
    timeSeriesBlob: list[TimeSeriesBlobKey] = Field(min_length=1)


class UsedTaskRuns(FewsModel):
    taskRun: list[TaskRunKey] = Field(min_length=1)


class UsedTasks(FewsModel):
    task: list[TaskKey] = Field(min_length=1)


class UsedModuleInstanceRuns(FewsModel):
    moduleInstanceRun: list[ModuleInstanceRunKey] = Field(min_length=1)


class UsedFewsSessions(FewsModel):
    fewsSession: list[FewsSessionKey] = Field(min_length=1)


class UsedWhatIfScenarios(FewsModel):
    whatIfScenario: list[WhatIfScenarioKey] = Field(min_length=1)


class UsedModifierDescriptors(FewsModel):
    modifierDescriptor: list[ModifierDescriptorKey] = Field(min_length=1)


class ArchiveMetaData(FewsModel):
    taskRunId: str
    dispatchTime: DateTimePair
    usedStates: UsedStates | None = None
    usedTimeSeriesBlobs: UsedTimeSeriesBlobs | None = None
    usedTaskRuns: UsedTaskRuns | None = None
    usedTasks: UsedTasks | None = None
    usedModuleInstanceRuns: UsedModuleInstanceRuns | None = None
    usedFewsSessions: UsedFewsSessions | None = None
    usedWhatIfScenarios: UsedWhatIfScenarios | None = None
    usedModifierDescriptors: UsedModifierDescriptors | None = None
    latestAvailableData: list[LatestAvailableData] = Field(default_factory=list)
    usedJre: str | None = None
    usedBuild: str | None = None
    usedConfigurationVersion: str | None = None
