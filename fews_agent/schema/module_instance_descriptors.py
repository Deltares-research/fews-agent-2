"""ModuleInstanceDescriptors.xml — declares moduleInstanceId with description.

Alongside the module config files (whose filename is also the id), this
file carries human-readable descriptions that the UI shows, plus a few
UI/runtime hints.

The XSD root is a choice-unbounded over three alternatives — individual
``moduleInstanceDescriptor``, grouping ``moduleInstanceGroup``, and the
CSV-source ``moduleInstanceDescriptorsCsvFile``. The CSV source is not
yet modelled; use the plain descriptor form for authored configs.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import CalendarTimeSpan, FewsModel
from .ids import ModuleInstanceId


class ModuleInstanceDescriptor(FewsModel):
    """One descriptor. ``moduleId`` is deprecated-and-obsolete since FEWS
    2013.02 (module is recognized from the config file's schema name) but
    still accepted for legacy configs."""

    id: ModuleInstanceId
    name: str | None = None
    description: str | None = None
    updateModuleRunTimesOnCompletion: bool | None = None
    moduleId: str | None = None
    simulatedHistoricalModuleInstanceId: str | None = None
    waterCoachExternalForecastDelay: CalendarTimeSpan | None = None


class ModuleInstanceGroup(FewsModel):
    """Groups descriptors under one id/name. Must contain at least one
    descriptor; flat descriptors at the root level are still allowed
    alongside groups."""

    id: str
    moduleInstanceDescriptor: list[ModuleInstanceDescriptor] = Field(min_length=1)
    name: str | None = None


class ModuleInstanceDescriptorAttributeFile(FewsModel):
    """Since 2022.01 — one attribute source for a CSV-sourced descriptors
    file. Referenced from ModuleInstanceDescriptorsCsvFile via id."""

    id: str
    csvFile: str
    description: str | None = None
    charset: str | None = None


class ModuleInstanceDescriptorsCsvFile(FewsModel):
    """Since 2022.01 — load descriptors from a CSV file. Column names
    are exposed here so the same CSV can drive descriptors in multiple
    files; the ``attributeFile`` entries add side-car CSVs with extra
    attributes keyed by the descriptor id."""

    file: str
    id: str
    charset: str | None = None
    name: str | None = None
    description: str | None = None
    group: str | None = None
    groupName: str | None = None
    updateModuleRunTimesOnCompletion: str | None = None
    simulatedHistoricalModuleInstanceId: str | None = None
    waterCoachExternalForecastDelayHours: str | None = None
    timeZoneOffset: str | None = None
    dateTimePattern: str | None = None
    attributeFile: list[ModuleInstanceDescriptorAttributeFile] = Field(default_factory=list)


class ModuleInstanceDescriptors(FewsModel):
    """Root of ModuleInstanceDescriptors.xml. Either flat descriptors,
    or groups, or CSV sources, or a mix — at least one is required."""

    moduleInstanceDescriptor: list[ModuleInstanceDescriptor] = Field(default_factory=list)
    moduleInstanceGroup: list[ModuleInstanceGroup] = Field(default_factory=list)
    moduleInstanceDescriptorsCsvFile: list[ModuleInstanceDescriptorsCsvFile] = Field(
        default_factory=list
    )
    version: str = "1.0"

    @model_validator(mode="after")
    def _at_least_one(self) -> ModuleInstanceDescriptors:
        if not (
            self.moduleInstanceDescriptor
            or self.moduleInstanceGroup
            or self.moduleInstanceDescriptorsCsvFile
        ):
            raise ValueError(
                "moduleInstanceDescriptors: supply at least one "
                "moduleInstanceDescriptor / moduleInstanceGroup / "
                "moduleInstanceDescriptorsCsvFile"
            )
        return self
