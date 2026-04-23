"""LisFlood.xml — LISFLOOD hydrological model adapter."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel


class LisFloodOutputFile(FewsModel):
    fileType: Literal["pcrastertimeseries", "pcrastermapstack"]
    file: str
    xmlFile: str
    conversionFile: str | None = None
    parameterID: str | None = None
    locationID: str | None = None
    locationIdPrefix: str | None = None


class LisFloodDirectories(FewsModel):
    inputDir: str
    workDir: str | None = None
    outputDir: str | None = None
    stateDir: str | None = None


class LisFloodAdapterFiles(FewsModel):
    stateFile: str | None = None
    parameterFile: str | None = None
    diagnosticFile: str | None = None
    inputMapStackFile: list[str] = Field(default_factory=list)
    outputFile: list[LisFloodOutputFile] = Field(default_factory=list)


class LisFloodModelFiles(FewsModel):
    LisFloodModFile: str
    logFile: str | None = None


class LisFlood(FewsModel):
    """Root of LisFlood.xml."""

    description: str | None = None
    directories: LisFloodDirectories
    adapterfiles: LisFloodAdapterFiles
    modelFiles: LisFloodModelFiles | None = None
    version: str = "1.1"
