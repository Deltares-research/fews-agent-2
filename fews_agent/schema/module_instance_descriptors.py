"""ModuleInstanceDescriptors.xml — declares moduleInstanceId with description.

Alongside the module config files (whose filename is also the id), this
file carries human-readable descriptions that the UI shows.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel
from .ids import ModuleInstanceId


class ModuleInstanceDescriptor(FewsModel):
    id: ModuleInstanceId
    description: str | None = None


class ModuleInstanceDescriptors(FewsModel):
    moduleInstanceDescriptor: list[ModuleInstanceDescriptor] = Field(min_length=1)
    version: str = "1.0"
