"""ForecasterNotesDisplay.xml — templated forecaster notes panel.

Full ForecasterNotesElements XSD group is modelled here. The same
group is reused by ``system_monitor_display.bulletinBoardPlus`` (FEWS
XSD ``<group ref="fews:ForecasterNotesElements"/>``).

XSD choice: ``messageTemplate[]`` (deprecated string form) XOR
``msgTemplate[]`` (typed form). At least one must be present per XSD.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import CalendarTimeSpan, FewsModel


class MsgTemplate(FewsModel):
    """MessageTemplateComplexType — id attr + MessageElements group."""

    id: str
    message: str
    messageWidth: int | None = None
    messageHeight: int | None = None


class EventCode(FewsModel):
    """Event code config — id attr + optional `<expiryTime>` calendar
    time span (since FEWS 2015.02) bounding log-message retention."""

    id: str
    expiryTime: CalendarTimeSpan | None = None


class NotesTableColumn(FewsModel):
    """One column of the notes table; just `<column visible="..."/>`."""

    visible: bool


class NotesTableColumns(FewsModel):
    """All ten columns of the notes table. Each ``visible`` is required
    when the column appears; ``taskRunId`` is optional at the XSD level."""

    logLevel: NotesTableColumn
    logCreationTime: NotesTableColumn
    expiryTime: NotesTableColumn
    eventCode: NotesTableColumn
    eventTime: NotesTableColumn
    userId: NotesTableColumn
    template: NotesTableColumn
    segment: NotesTableColumn
    logMessage: NotesTableColumn
    taskRunId: NotesTableColumn | None = None


class Note(FewsModel):
    """XSD NoteComplexType — eventCodeId + messageTemplateId + optional name attr."""

    eventCodeId: str
    messageTemplateId: str
    name: str | None = None


class TextNote(Note):
    """XSD TextNoteComplexType — Note with extra display knobs."""

    keepText: bool | None = None
    maxNumberOfLines: int | None = Field(default=None, ge=1)
    maxNumberOfCharactersInLine: int | None = Field(default=None, ge=1)


class NoteChoice(FewsModel):
    name: str
    note: list[Note] = Field(min_length=1)


class NoteChoiceGroup(FewsModel):
    noteChoice: list[NoteChoice] = Field(min_length=1)
    name: str | None = None


class NoteGroup(FewsModel):
    """XSD ``choice maxOccurs=unbounded`` over note / noteChoiceGroup /
    viewPermission / createPermission.  Modelled as parallel lists /
    optional fields — XSD accepts any interleaving."""

    name: str
    id: str | None = None
    note: list[TextNote] = Field(default_factory=list)
    noteChoiceGroup: list[NoteChoiceGroup] = Field(default_factory=list)
    viewPermission: str | None = None
    createPermission: str | None = None


class MultipleForecasterNotesMaker(FewsModel):
    noteGroup: list[NoteGroup] = Field(min_length=1)


class ForecasterNotesElements(FewsModel):
    """Full ForecasterNotesElements XSD group (reused by SystemMonitor's
    bulletinBoardPlus). Validator enforces the msgTemplate-vs-
    messageTemplate choice."""

    columns: NotesTableColumns | None = None
    maxNumberOfLinesInTableRow: int | None = Field(default=None, ge=0)
    defaultTopologyNodeId: str | None = None
    defaultAreaId: str | None = None
    messageTemplate: list[str] = Field(default_factory=list)
    msgTemplate: list[MsgTemplate] = Field(default_factory=list)
    eventCode: list[EventCode] = Field(default_factory=list)
    userTemplate: list[str] = Field(default_factory=list)
    multipleForecasterNotesMaker: MultipleForecasterNotesMaker | None = None

    @model_validator(mode="after")
    def _one_template_variant(self) -> ForecasterNotesElements:
        has_deprecated = bool(self.messageTemplate)
        has_typed = bool(self.msgTemplate)
        if has_deprecated == has_typed:
            raise ValueError(
                "forecasterNotesElements: supply exactly one of "
                "messageTemplate[] (deprecated) or msgTemplate[]"
            )
        return self


class ForecasterNotesDisplay(ForecasterNotesElements):
    """Root of ForecasterNotesDisplay.xml.

    Extends ForecasterNotesElements with a required title and optional
    deletePermission (since FEWS 2024.02).
    """

    title: str
    deletePermission: str | None = None
