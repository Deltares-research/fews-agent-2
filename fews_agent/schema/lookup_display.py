"""LookupDisplay.xml — lookup-table display for critical-condition lookup."""
from __future__ import annotations

from pydantic import Field

from .common import DataVariable, FewsModel


class LookupDisplayGeneral(FewsModel):
    reportDirectory: str
    externalBrowser: str | None = None


class LookupDisplayDescriptor(FewsModel):
    descriptorId: str
    description: str | None = None
    workflowDescriptorId: str
    prefixwhatifScenarioDescriptorID: str | None = None
    inputVariable: list[DataVariable] = Field(min_length=1)
    outputVariable: DataVariable
    subDir: str | None = None
    reportFileName: str


class LookupDisplay(FewsModel):
    """Root of LookupDisplay.xml."""

    general: LookupDisplayGeneral
    lookupDisplayDescriptor: list[LookupDisplayDescriptor] = Field(min_length=1)
    version: str = "1.1"
