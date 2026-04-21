"""ForecasterNotesDisplay.xml — templated forecaster notes panel."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class MsgTemplate(FewsModel):
    id: str
    message: str


class EventCode(FewsModel):
    """Event code reference — the element carries only an id attribute
    in XML (`<eventCode id="General.info"/>`)."""

    id: str


class ForecasterNotesDisplay(FewsModel):
    """Root of ForecasterNotesDisplay.xml."""

    title: str | None = None
    msgTemplate: list[MsgTemplate] = Field(default_factory=list)
    eventCode: list[EventCode] = Field(default_factory=list)
