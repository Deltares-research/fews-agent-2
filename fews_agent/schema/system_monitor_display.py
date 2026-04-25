"""SystemMonitorDisplay.xml — System Monitor window configuration.

Four optional tabs — importStatus, exportStatus, bulletinBoard,
bulletinBoardPlus. The bulletinBoardPlus variant extends the plain
bulletinBoard with the ``ForecasterNotesElements`` group from
``forecasterNotesDisplay.xsd`` — imported directly from
``forecaster_notes_display`` so the two files share one model.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import CalendarTimeSpan, FewsModel, RelativeTime
from .forecaster_notes_display import ForecasterNotesElements


Tab = Literal[
    "logBrowser", "bulletinBoard", "bulletinBoardPlus", "batchTasks",
    "importStatus", "liveStatus", "scheduledTasks", "runningTasks",
    "synchStatus", "synchLog",
]
LogLevel = Literal["DEBUG", "INFO", "WARN", "ERROR", "FATAL"]


class TimeThreshold(FewsModel):
    periodLength: RelativeTime
    color: str  # colorStringType
    eventCode: str | None = None
    logLevel: LogLevel | None = None
    graceTime: CalendarTimeSpan | None = None


class DefaultTimeThreshold(FewsModel):
    timeThreshold: list[TimeThreshold] = Field(min_length=1)


class TransferStatusDataFeed(FewsModel):
    id: str
    name: str | None = None
    description: str | None = None
    timeThreshold: list[TimeThreshold] = Field(min_length=1)


class DeprecatedExtraTimeThreshold(FewsModel):
    """Deprecated — use dataFeed instead."""

    dataFeedId: str
    timeThreshold: list[TimeThreshold] = Field(min_length=1)


class VisibleColumns(FewsModel):
    workflow: bool | None = None
    taskRun: bool | None = None
    suspended: bool | None = None


class SystemMonitorTransferStatus(FewsModel):
    """Shared shape for importStatus and exportStatus. Final element is
    an XSD choice: dataFeed[] XOR extraTimeThreshold[] (deprecated)."""

    tabName: str
    defaultTimeThreshold: DefaultTimeThreshold
    description: str | None = None
    tabMnemonic: str | None = None
    visibleColumns: VisibleColumns | None = None
    dataFeed: list[TransferStatusDataFeed] = Field(default_factory=list)
    extraTimeThreshold: list[DeprecatedExtraTimeThreshold] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_tail(self) -> SystemMonitorTransferStatus:
        if self.dataFeed and self.extraTimeThreshold:
            raise ValueError(
                "transferStatus: dataFeed and extraTimeThreshold are mutually "
                "exclusive"
            )
        return self


class SystemMonitorBulletinBoard(FewsModel):
    tabName: str
    description: str | None = None
    tabMnemonic: str | None = None


class SystemMonitorBulletinBoardPlus(SystemMonitorBulletinBoard):
    """Extends the plain bulletinBoard with the ForecasterNotesElements
    group.  Required because the XSD group has a required msgTemplate /
    messageTemplate choice."""

    notes: ForecasterNotesElements


class SystemMonitorDisplay(FewsModel):
    description: str | None = None
    defaultSelectedTab: Tab | None = None
    importStatus: SystemMonitorTransferStatus | None = None
    exportStatus: SystemMonitorTransferStatus | None = None
    bulletinBoard: SystemMonitorBulletinBoard | None = None
    bulletinBoardPlus: SystemMonitorBulletinBoardPlus | None = None
