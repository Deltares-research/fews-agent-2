"""ArchiveRun.xml — inactive archive-run config.

Marked ``INACTIVE`` in the XSD. Optional choice between import- and
export-archive activity. The ``exportArchiveRun`` branch carries most
of the payload (period filters, workflow scopes, log-event constraints).

``ArchiveType`` enum and ``LogEventConstraint`` attribute-bag are
both local to this file.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import FewsModel, RelativePeriod, UnitMultiplier


ArchiveType = Literal[
    "ForecastArchive",
    "ThresholdEventsArchive",
    "TimeSeriesArchive",
    "ConfigurationArchive",
    "LogEntriesArchive",
]


class LogEventConstraint(FewsModel):
    eventCode: str | None = None
    messageText: str | None = None


class ExportArchiveRun(FewsModel):
    archivePeriod: RelativePeriod
    workflow: list[str] = Field(default_factory=list)
    exportToFile: bool | None = None
    exportToDatabase: bool | None = None
    overrulingPeriod: RelativePeriod | None = None
    excludeTimeSeriesExpiringWithin: UnitMultiplier | None = None
    onlyApproved: bool | None = None
    archiveType: ArchiveType | None = None
    logEventConstraint: list[LogEventConstraint] = Field(default_factory=list)
    description: str | None = None
    includeModuleInstanceId: list[str] = Field(default_factory=list)


class ImportArchiveRun(FewsModel):
    archiveType: ArchiveType | None = None
    includeGrids: bool | None = None


class ArchiveRun(FewsModel):
    """XSD choice: at most one of ``importArchiveRun`` / ``exportArchiveRun``
    (both branches are optional)."""

    importDirectory: str | None = None
    exportDirectory: str | None = None
    importArchiveRun: ImportArchiveRun | None = None
    exportArchiveRun: ExportArchiveRun | None = None

    @model_validator(mode="after")
    def _at_most_one(self) -> ArchiveRun:
        if self.importArchiveRun is not None and self.exportArchiveRun is not None:
            raise ValueError(
                "archiveRun: at most one of importArchiveRun / exportArchiveRun"
            )
        return self
