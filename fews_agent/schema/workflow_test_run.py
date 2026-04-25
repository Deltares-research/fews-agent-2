"""WorkflowTestRun.xml — workflow test configuration.

Top-level ``<activities>`` is a ``choice maxOccurs=unbounded`` over 11
activity kinds (purge / copy / workflow / checkPerformance / exportTs /
exportLogs / setSystemTime / compare / refresh / contains / notContains /
sleep). Modelled as parallel lists — XSD accepts any interleaving.

``WftrWorkflowActivity`` itself has an inner XSD choice: either the
``WftrWorkflowGroup`` fields (workflowId + optional systemTime +
optional warmStateSearchPeriod) or a full ``<taskProperties>`` block.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import FewsModel, Period, TimeSeriesSet, UnitMultiplier
from .archive_metadata import DateTimePair
from .task_properties import TaskProperties


LogLevel = Literal["DEBUG", "INFO", "WARN", "ERROR", "FATAL"]
ReportType = Literal["junitXml"]


class WftrDirDefinition(FewsModel):
    """Attribute-only ``<dirDefinition refName="..." dir="..."/>``."""

    refName: str | None = None
    dir: str | None = None


class WftrTestReport(FewsModel):
    reportType: ReportType
    dir: str | None = None


class WftrGeneral(FewsModel):
    description: str | None = None
    dirDefinition: list[WftrDirDefinition] = Field(default_factory=list)
    systemTime: DateTimePair | None = None
    testReport: WftrTestReport | None = None


class WftrPurgeActivity(FewsModel):
    filter: str
    description: str | None = None
    maxAge: UnitMultiplier | None = None


class WftrCopyActivity(FewsModel):
    src: str
    dest: str
    description: str | None = None


class WftrCompareActivity(FewsModel):
    exportFile: str
    compareFile: str
    description: str | None = None


class WftrWorkflowActivity(FewsModel):
    """Inner XSD choice: the WftrWorkflowGroup (workflowId + optional
    systemTime + optional warmStateSearchPeriod) vs. a full taskProperties."""

    workflowId: str | None = None
    systemTime: DateTimePair | None = None
    warmStateSearchPeriod: Period | None = None
    taskProperties: TaskProperties | None = None

    @model_validator(mode="after")
    def _one_form(self) -> WftrWorkflowActivity:
        has_group = self.workflowId is not None
        has_task = self.taskProperties is not None
        if has_group == has_task:
            raise ValueError(
                "workflowActivity: supply exactly one of (workflowId + optional "
                "systemTime / warmStateSearchPeriod) or taskProperties"
            )
        return self


class WftrCheckPerformanceActivity(FewsModel):
    workflowId: str
    maximumRuntime: UnitMultiplier
    systemTime: DateTimePair | None = None


class WftrTimeSeriesSets(FewsModel):
    timeSeriesSet: list[TimeSeriesSet] = Field(min_length=1)


class WftrExportTimeSeriesActivity(FewsModel):
    exportFile: str
    timeSeriesSets: WftrTimeSeriesSets
    description: str | None = None
    exportBinFile: bool | None = None
    omitMissingValues: bool | None = None
    piVersion: str | None = None


class WftrExportLogsActivity(FewsModel):
    exportFile: str
    description: str | None = None
    logLevel: LogLevel | None = None
    moduleInstanceId: str | None = None


class WftrSetSystemTimeActivity(FewsModel):
    systemTime: DateTimePair
    description: str | None = None


class WftrTextMatchActivity(FewsModel):
    """Shared shape for ``containsActivity`` and ``notContainsActivity``.
    XSD choice: searchString+ XOR emptyFile (bool flag)."""

    searchFile: str
    description: str | None = None
    searchString: list[str] = Field(default_factory=list)
    emptyFile: bool = False

    @model_validator(mode="after")
    def _one_form(self) -> WftrTextMatchActivity:
        has_strings = bool(self.searchString)
        if has_strings == self.emptyFile:
            raise ValueError(
                "contains/notContainsActivity: supply exactly one of "
                "searchString[] or emptyFile=True"
            )
        return self


class WftrSleepActivity(FewsModel):
    sleepTimeMillis: int
    description: str | None = None


class WftrActivities(FewsModel):
    """XSD choice-unbounded over 11 activity kinds.  ``refreshActivity``
    is typed ``anyType`` — we expose it as an optional literal-True bag
    with no body content (empty ``<refreshActivity/>`` tags)."""

    purgeActivity: list[WftrPurgeActivity] = Field(default_factory=list)
    copyActivity: list[WftrCopyActivity] = Field(default_factory=list)
    workflowActivity: list[WftrWorkflowActivity] = Field(default_factory=list)
    checkPerformanceActivity: list[WftrCheckPerformanceActivity] = Field(default_factory=list)
    exportTimeSeriesActivity: list[WftrExportTimeSeriesActivity] = Field(default_factory=list)
    exportLogsActivity: list[WftrExportLogsActivity] = Field(default_factory=list)
    setSystemTimeActivity: list[WftrSetSystemTimeActivity] = Field(default_factory=list)
    compareActivity: list[WftrCompareActivity] = Field(default_factory=list)
    refreshActivity: int = 0
    containsActivity: list[WftrTextMatchActivity] = Field(default_factory=list)
    notContainsActivity: list[WftrTextMatchActivity] = Field(default_factory=list)
    sleepActivity: list[WftrSleepActivity] = Field(default_factory=list)


class WorkflowTestRun(FewsModel):
    general: WftrGeneral
    activities: WftrActivities
