"""SobekModel.xml — SOBEK hydrodynamic model adapter.

Reuses AdapterMapping from sacramento_model since SOBEK's <mapping>
element uses the same sharedTypes AdapterMappingComplexType.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel
from .sacramento_model import AdapterMapping


class SobekAdapterFiles(FewsModel):
    stateFile: str | None = None
    diagnosticFile: str | None = None
    branchFile: str | None = None
    controlsDefTemplateFile: str | None = None
    triggersDefTemplateFile: str | None = None


class SobekFolderNames(FewsModel):
    configDir: str
    workDir: str
    purgeWorkDir: bool | None = None
    moduleDir: str
    importDir: str
    exportDir: str
    purgeExportDir: bool | None = None


class SobekModelFiles(FewsModel):
    useNefis4: bool | None = None
    mdaFile: str
    dataFile: str
    definitionFile: str | None = None
    rstDataClusterFile: str | None = None
    modelRunPeriodFile: str | None = None
    logFile: str | None = None
    hisFile: list[str] = Field(default_factory=list)
    mapFile: str | None = None
    returnFile: str | None = None


class SobekModel(FewsModel):
    """Root of SobekModel.xml."""

    description: str | None = None
    directories: SobekFolderNames
    adapterfiles: SobekAdapterFiles
    modelFiles: SobekModelFiles
    mapping: list[AdapterMapping] = Field(default_factory=list)
    version: str = "1.1"
