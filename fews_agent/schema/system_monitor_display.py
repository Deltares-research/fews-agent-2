"""SystemMonitorDisplay.xml — System Monitor window configuration.

Four optional tabs — importStatus, exportStatus, bulletinBoard,
bulletinBoardPlus. The bulletinBoardPlus variant extends the plain
bulletinBoard with the ``ForecasterNotesElements`` group from
``forecasterNotesDisplay.xsd``. We model that group locally (compact
subset) — reusing the existing ``ForecasterNotesDisplay`` model would
require upgrading it, which could regress tutorial configs.

The minimal subset covers:
  - optional ``columns``, ``maxNumberOfLinesInTableRow``,
    ``defaultTopologyNodeId``, ``defaultAreaId``
  - required ``messageTemplate`` (simple string) XOR ``msgTemplate``
    (id + MessageElements) choice — at least one msgTemplate /
    messageTemplate must be supplied per XSD
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import CalendarTimeSpan, FewsModel, RelativeTime


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


class MessageTemplate(FewsModel):
    """Inlined MsgTemplate — id + MessageElements group."""

    id: str
    message: str
    messageWidth: int | None = None
    messageHeight: int | None = None


class ForecasterNotesElements(FewsModel):
    """Compact subset of the ForecasterNotesElements XSD group, enough
    for bulletinBoardPlus. Exactly one of messageTemplate (string list)
    or msgTemplate (object list) is required per the XSD."""

    messageTemplate: list[str] = Field(default_factory=list)
    msgTemplate: list[MessageTemplate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_template(self) -> ForecasterNotesElements:
        has_simple = bool(self.messageTemplate)
        has_obj = bool(self.msgTemplate)
        if has_simple == has_obj:
            raise ValueError(
                "forecasterNotesElements: supply exactly one of "
                "messageTemplate[] or msgTemplate[]"
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
