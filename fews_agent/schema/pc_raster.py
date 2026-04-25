"""PcRaster.xml — config for the PCRaster model adapter.

Same directories / adapterfiles / modelFiles shape as the other model
adapters (Sacramento, LisFlood, Ribasim, Sobek, SouthernTransferFunctions).
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel


PCRasterFileType = Literal[
    "pcrastertimeseries",
    "pcrastermaps",
    "pitimeseries",
    "pimapstack",
    "pitimeseriesSkipFirstTimeStep",
]


class PCRasterDirectories(FewsModel):
    workDir: str | None = None
    inputDir: str
    outputDir: str
    stateDir: str | None = None
    longTermAverageInputDir: str | None = None


class PCRasterFile(FewsModel):
    """One ``<inputFile/>`` or ``<outputFile/>`` — all attributes on the
    element, no child content. ``fileType`` / ``file`` / ``xmlFile`` are
    XSD-required; the rest are optional."""

    fileType: PCRasterFileType
    file: str
    xmlFile: str
    conversionFile: str | None = None
    parameterID: str | None = None
    locationIdPrefix: str | None = None
    locationID: str | None = None


class PCRasterLongTermAverageInputFile(FewsModel):
    inputFile: str
    outputFile: str


class PCRasterAdapterFiles(FewsModel):
    stateFile: str | None = None
    parameterFile: str | None = None
    inputFile: list[PCRasterFile] = Field(default_factory=list)
    outputFile: list[PCRasterFile] = Field(min_length=1)
    diagnosticFile: str | None = None
    inputMapStackFile: list[str] = Field(default_factory=list)
    longTermAverageInputFile: list[PCRasterLongTermAverageInputFile] = Field(
        default_factory=list
    )


class PCRasterModelFiles(FewsModel):
    """XSD choice: exactly one of ``pcrasterModFile`` or ``pcrasterXMLFile``."""

    pcrasterModFile: str | None = None
    pcrasterXMLFile: str | None = None
    logFile: str | None = None
    timeShiftFromMonthDay: str | None = None


class PCRaster(FewsModel):
    """Root of PcRaster.xml."""

    version: str = "1.1"
    description: str | None = None
    directories: PCRasterDirectories
    adapterfiles: PCRasterAdapterFiles
    modelFiles: PCRasterModelFiles
