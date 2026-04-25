"""LogDisplays.xml — Web OC log display configuration."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel, RelativeViewPeriod


SystemLogLevel = Literal["ERROR", "WARN", "INFO"]


class LogDisplaySystemEventCodes(FewsModel):
    eventCode: list[str] = Field(min_length=1)


class LogDisplaySystemLog(FewsModel):
    enabled: bool | None = None
    logLevel: SystemLogLevel | None = None
    eventCodes: LogDisplaySystemEventCodes | None = None


class LogDisplayManualLog(FewsModel):
    enabled: bool | None = None
    noteGroupId: str | None = None
    createPermission: str | None = None


class LogDisplayLogDisseminationAction(FewsModel):
    id: str
    description: str
    iconId: str
    eventCode: str
    manualLog: bool | None = None
    systemLog: bool | None = None
    maxLogCharacters: int | None = None
    permission: str | None = None


class LogDisplayLogDisseminationActions(FewsModel):
    action: list[LogDisplayLogDisseminationAction] = Field(min_length=1)
    permission: str | None = None


class LogDisplayLogDissemination(FewsModel):
    enabled: bool | None = None
    disseminationActions: LogDisplayLogDisseminationActions | None = None
    permission: str | None = None


class LogDisplay(FewsModel):
    id: str
    name: str
    relativeViewPeriod: RelativeViewPeriod | None = None
    defaultLogRequestCount: int | None = None
    systemLog: LogDisplaySystemLog | None = None
    manualLog: LogDisplayManualLog | None = None
    logDissemination: LogDisplayLogDissemination | None = None
    viewPermission: str | None = None


class LogDisplays(FewsModel):
    logDisplay: list[LogDisplay] = Field(min_length=1)
