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


class ArchiveMetaData(FewsModel):
    taskRunId: str
    dispatchTime: DateTimePair
    usedStates: list[WarmStateKey] = Field(default_factory=list)
    usedTimeSeriesBlobs: list[TimeSeriesBlobKey] = Field(default_factory=list)
    usedTaskRuns: list[TaskRunKey] = Field(default_factory=list)
    usedTasks: list[TaskKey] = Field(default_factory=list)
    usedModuleInstanceRuns: list[ModuleInstanceRunKey] = Field(default_factory=list)
    usedFewsSessions: list[FewsSessionKey] = Field(default_factory=list)
    usedWhatIfScenarios: list[WhatIfScenarioKey] = Field(default_factory=list)
    usedModifierDescriptors: list[ModifierDescriptorKey] = Field(default_factory=list)
    latestAvailableData: list[LatestAvailableData] = Field(default_factory=list)
    usedJre: str | None = None
    usedBuild: str | None = None
    usedConfigurationVersion: str | None = None
