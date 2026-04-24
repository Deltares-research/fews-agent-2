"""McSynchronisation.xml — MC-to-MC synchronisation record-type filter.

Root element is ``<synchronisation>``. Each ``recordtype`` carries a
type enum + optional ``<modifier>`` wrapping synchLevels.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel


McRecordType = Literal[
    "SystemActivities",
    "AccessKeyHashes",
    "BaseBuildFileSets",
    "BaseBuildFiles",
    "CMConfigFiles",
    "ComponentLogFileSnapshots",
    "FewsWebServices",
    "FssResources",
    "FssStatus",
    "MCConfigFiles",
    "TaskRunLogFiles",
    "UserSettings",
    "UserToGroupsMappings",
    "Users",
    "MasterControllers",
    "LiveMcAvailabilities",
    "ForecastingShells",
    "DeletedRows",
    "WorkflowFiles",
    "SystemConfigurations",
    "ModuleInstanceConfigs",
    "ModuleInstanceDatasets",
    "RegionConfigurations",
    "DisplayConfigurations",
    "FlagConversions",
    "IdMaps",
    "UnitConversions",
    "ReportTemplates",
    "CorrelationEventSets",
    "CorrelationTravelTimes",
    "MapLayers",
    "Icons",
    "ReportImages",
    "RootConfigFiles",
    "PiServiceConfigurations",
    "PiClientConfigurations",
    "ModuleParameters",
    "CoefficientSets",
    "WhatIfScenarios",
    "Tasks",
    "TaskRuns",
    "FewsSessions",
    "MCCpts",
    "LogEntries",
    "ModuleInstanceRuns",
    "TaskRunCompletions",
    "ArchiveMetadata",
    "Reports",
    "WarmStates",
    "ColdStates",
    "DefaultColdStates",
    "TimeSeries",
    "ThresholdEvents",
    "ConfigRevisionSets",
    "Modifiers",
    "ModuleParameterModifiers",
    "McFailoverPriorities",
    "PiClientDataSets",
    "AttributeModifiers",
    "HistoricalEvents",
    "Samples",
    "ModuleRunTables",
    "FloodPeriods",
    "ImportStatus",
    "FssGroups",
]


class McSynchLevel(FewsModel):
    """`<synchlevel level="..."/>` — `level` is an `idIntType` (int)."""

    level: int


class McModifier(FewsModel):
    synchlevel: list[McSynchLevel] = Field(default_factory=list)


class McRecordTypeEntry(FewsModel):
    type: McRecordType
    modifier: McModifier | None = None


class McRemoteMcId(FewsModel):
    name: str


class McSynchId(FewsModel):
    id: str


class McSynchParams(FewsModel):
    remotemcid: McRemoteMcId
    synchid: McSynchId


class McSynchronisation(FewsModel):
    """Root of MC-synchronisation config (`<synchronisation>` element)."""

    synchparams: McSynchParams
    recordtype: list[McRecordTypeEntry] = Field(default_factory=list)
