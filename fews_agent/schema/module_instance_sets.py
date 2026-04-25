"""ModuleInstanceSets.xml — named bundles of moduleInstanceIds.

Used by workflows and maintenance jobs to operate on groups of modules.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel
from .ids import ModuleInstanceId, ModuleInstanceSetId


class ModuleInstanceSet(FewsModel):
    id: ModuleInstanceSetId
    name: str | None = None
    description: str | None = None
    moduleInstanceId: list[ModuleInstanceId] = Field(default_factory=list)
    moduleInstanceIdPattern: list[str] = Field(default_factory=list)


class ModuleInstanceSets(FewsModel):
    """Root of ModuleInstanceSets.xml."""

    moduleInstanceSet: list[ModuleInstanceSet] = Field(min_length=1)
    version: str = "1.1"
