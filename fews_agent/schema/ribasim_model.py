"""RibasimModel.xml — Ribasim water-allocation model adapter."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel


class RibasimFile(FewsModel):
    type: Literal["tms", "par"]
    fileOut: str
    fileIn: str
    conversionfile: str | None = None
    headerId: str | None = None
    unit: int | None = None


class RibasimFileHeader(FewsModel):
    text: str
    id: str | None = None


class RibasimFolderNames(FewsModel):
    workDir: str | None = None
    inputDir: str | None = None
    outputDir: str | None = None
    stateDir: str | None = None


class RibasimAdapterFiles(FewsModel):
    stateFile: str | None = None
    inputFile: list[RibasimFile] = Field(default_factory=list)
    outputFile: list[RibasimFile] = Field(default_factory=list)
    diagnosticFile: str | None = None


class RibasimModelFiles(FewsModel):
    logFile: str | None = None


class RibasimModel(FewsModel):
    """Root of RibasimModel.xml."""

    description: str | None = None
    simulationTimestep: Literal["month", "halfmonth", "decade", "week"] | None = None
    ribasimVersion: str | None = None
    fileHeaders: list[RibasimFileHeader] = Field(default_factory=list)
    directories: RibasimFolderNames
    adapterfiles: RibasimAdapterFiles
    modelFiles: RibasimModelFiles
    version: str = "1.1"
