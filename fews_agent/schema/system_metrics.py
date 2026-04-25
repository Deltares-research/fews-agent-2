"""SystemMetrics.xml — DDA system metrics collection.

Stores row/byte counts and status values as time series. Sections
are all optional except ``general``.

``TimeSpanComplexType`` (attribute-only unit/multiplier/divider) uses
the same shape as ``CalendarTimeSpan`` — we reuse that model since
the XSD unit enum just restricts which units are legal, not the
element structure.
"""
from __future__ import annotations

from pydantic import Field

from .common import CalendarTimeSpan, FewsModel


class SystemMetricGeneral(FewsModel):
    locationId: str
    synchLevel: str | None = None  # intStringType — keep as str for placeholders
    expiryTime: CalendarTimeSpan | None = None


class DatabaseMetric(FewsModel):
    rowCountParameterId: str | None = None
    byteCountParameterId: str | None = None


class TableMetric(FewsModel):
    tableName: str
    rowCountParameterId: str | None = None
    byteCountParameterId: str | None = None
    maximalAge: CalendarTimeSpan | None = None
    minimalAge: CalendarTimeSpan | None = None
    lifeSpan: CalendarTimeSpan | None = None


class LogEntryMetric(FewsModel):
    rowCountParameterId: str
    logLevel: str | None = None
    eventCode: str | None = None
    maximalAge: CalendarTimeSpan | None = None
    minimalAge: CalendarTimeSpan | None = None
    lifeSpan: CalendarTimeSpan | None = None


class MCStatusMetric(FewsModel):
    failedOverParameterId: str | None = None
    aliveRemoteMcCountParameterId: str | None = None
    taskQueueLengthParameterId: str | None = None
    activeTasksCountParameterId: str | None = None
    ocSessionsCountParameterId: str | None = None
    liveComponentCountParameterId: str | None = None
    oclListenerParameterId: str | None = None
    fslListenerParameterId: str | None = None
    synchListenerParameterId: str | None = None
    synchRunnerParameterId: str | None = None
    synchTaskListenerParameterId: str | None = None
    tmLauncherParameterId: str | None = None
    tmChaserParameterId: str | None = None
    tmLogProcessorParameterId: str | None = None
    sysMonListenerParameterId: str | None = None
    sysMonMonitorParameterId: str | None = None
    sysMonHeartbeatParameterId: str | None = None


class FSSStatusMetric(FewsModel):
    """Deprecated since 2018.02 — still schema-valid."""

    buildVersionParameterId: str | None = None
    queueLengthParameterId: str | None = None
    downParameterId: str | None = None


class WorkflowMetric(FewsModel):
    workflowId: list[str] = Field(min_length=1)
    timeSeriesByteCountParameterId: str | None = None
    timeSeriesRowCountParameterId: str | None = None
    taskRunDurationParameterId: str | None = None
    maximalAge: CalendarTimeSpan | None = None
    minimalAge: CalendarTimeSpan | None = None


class SystemMetrics(FewsModel):
    general: SystemMetricGeneral
    database: DatabaseMetric | None = None
    table: list[TableMetric] = Field(default_factory=list)
    logEntry: list[LogEntryMetric] = Field(default_factory=list)
    mcStatus: MCStatusMetric | None = None
    fssStatus: FSSStatusMetric | None = None
    workflow: list[WorkflowMetric] = Field(default_factory=list)
