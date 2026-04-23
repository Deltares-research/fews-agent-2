"""Launcher.xml — FEWS launcher UI (multiple actions, each with
webPage / javaApp / executable entries).

javaApp is 'No longer supported from 2018.02' per the XSD annotation;
we model it for backward-compat since the XSD still accepts it.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import FewsModel


OperationMode = Literal["StandAlone", "OnLine", "OffLine", "Development", "Test"]


class LauncherWebPage(FewsModel):
    name: str
    appPath: str
    arg: str


class LauncherJavaApp(FewsModel):
    """Legacy form (pre-2018.02); still valid per XSD."""

    region: str
    operationMode: OperationMode
    operationModeCaption: str | None = None
    operationModeHidden: bool | None = None
    path: str | None = None
    javaClass: str | None = None
    jvmOption: str | None = None
    argument: str | None = None


class LauncherExecutable(FewsModel):
    """2018.02+ form — preferred over javaApp."""

    appPath: str
    region: str
    operationMode: OperationMode
    operationModeCaption: str | None = None
    operationModeHidden: bool | None = None
    arguments: list[str] = Field(default_factory=list)


class LauncherAction(FewsModel):
    """XSD choice wrapper: exactly one of webPage[], javaApp[], executable[]."""

    id: str
    buttonText: str | None = None
    description: str | None = None
    webPage: list[LauncherWebPage] = Field(default_factory=list)
    javaApp: list[LauncherJavaApp] = Field(default_factory=list)
    executable: list[LauncherExecutable] = Field(default_factory=list)

    @model_validator(mode="after")
    def _exactly_one_kind(self) -> LauncherAction:
        kinds = [bool(self.webPage), bool(self.javaApp), bool(self.executable)]
        if sum(kinds) != 1:
            raise ValueError(
                "launcher/action: supply exactly one of webPage[], javaApp[], executable[]"
            )
        return self


class Launcher(FewsModel):
    """Root of Launcher.xml."""

    language: Annotated[str, Field(max_length=2)] | None = None
    title: str | None = None
    action: list[LauncherAction] = Field(min_length=1)
