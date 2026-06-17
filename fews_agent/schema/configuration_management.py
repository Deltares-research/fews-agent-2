"""ConfigurationManagement.xml — Config Manager UI config (table→file-type mappings)."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel


class ConfigParams(FewsModel):
    defaultXmlEditor: str
    defaultHtmlEditor: str
    directPrimaryValidation: bool
    analysisMatchLimit: int


class ConfigChildType(FewsModel):
    name: str


class ConfigGroup(FewsModel):
    title: str
    tableName: str
    columnName: str
    subDirectory: str
    dataRelationType: Literal["ROOTNODE", "ONETOONE", "ONETOMANY", "MANYTOMANY"]
    fileType: Literal["NONE", "XML", "HTML", "ZIP", "MAPS", "IMAGES", "TXT"]
    childType: list[ConfigChildType] = Field(default_factory=list)
    configTypeContainsSpace: bool | None = None


class ConfigExcludedWorkflows(FewsModel):
    """`<excludedWorkflows>` wrapper around `<workflowName>` elements."""

    workflowName: list[str] = Field(min_length=1)


class ConfigurationManagement(FewsModel):
    """Root of ConfigurationManagement.xml."""

    configParams: ConfigParams
    configGroup: list[ConfigGroup] = Field(min_length=1)
    excludedWorkflows: ConfigExcludedWorkflows | None = None
    version: str = "1.0"
