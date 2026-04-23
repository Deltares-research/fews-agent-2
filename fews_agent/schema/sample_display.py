"""SampleDisplay.xml — configures the Sample Viewer UI."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class ModuleInstancePermission(FewsModel):
    id: str
    viewPermission: str


class SampleDisplayPermissions(FewsModel):
    editorPermission: str | None = None
    moduleInstance: list[ModuleInstancePermission] = Field(default_factory=list)


class SampleDisplaySeason(FewsModel):
    """XSD SeasonComplexType — a date range that repeats yearly."""

    startMonthDay: str  # --MM-DD
    endMonthDay: str
    timeZone: str | None = None
    label: str | None = None


class SampleDisplay(FewsModel):
    """Root of SampleDisplay.xml."""

    enableEditor: bool | None = None
    permissions: SampleDisplayPermissions | None = None
    season: list[SampleDisplaySeason] = Field(default_factory=list)
