"""TabularConfigFilesDisplay.xml — tabular viewer for config files with
optional per-task executable buttons (since 2024.01)."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class EnvironmentVariable(FewsModel):
    name: str
    value: str


class Arguments(FewsModel):
    """`<arguments>` wrapper around `<argument>` elements."""

    argument: list[str] = Field(default_factory=list)


class EnvironmentVariables(FewsModel):
    """`<environmentVariables>` wrapper around `<environmentVariable>`."""

    environmentVariable: list[EnvironmentVariable] = Field(default_factory=list)


class TabularConfigFilesDisplayTask(FewsModel):
    name: str
    iconFile: str
    workDir: str
    executable: str
    description: str | None = None
    permission: str | None = None
    arguments: Arguments | None = None
    environmentVariables: EnvironmentVariables | None = None


class TabularConfigFilesDisplay(FewsModel):
    """Root of TabularConfigFilesDisplay.xml."""

    editPermission: str | None = None
    taskButton: list[TabularConfigFilesDisplayTask] = Field(default_factory=list)
