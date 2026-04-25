"""HbvModel.xml — HBV hydrological model adapter.

Seventh model-adapter generator. Same directories / adapterfiles /
modelFiles pattern as Sacramento / LisFlood / Ribasim / Sobek /
SouthernTransferFunctions / PcRaster, plus optional variables and
actionSpec sections specific to HBV.

The XSD ``HbvVariableEnumStringType`` allows ``true`` / ``false`` /
``ask`` — wider than a boolean — so those fields stay as strings.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel


HbvVariable = Literal["true", "false", "ask"]
HbvActionSpec = Literal["noStateFileUpdate", "noStateFileCopy", "autoCorrectStateTimes"]


class HbvModelDirectories(FewsModel):
    """Inner ``<modelDirectories>`` block."""

    rootDir: str | None = None
    keyDir: str | None = None
    districtDir: str | None = None
    stateDir: str | None = None


class HbvFolderNames(FewsModel):
    configDir: str
    adapterDir: str
    modelDirectories: HbvModelDirectories | None = None
    importDir: str | None = None
    exportDir: str | None = None
    workDir: str | None = None


class HbvModelPropertiesFiles(FewsModel):
    """XSD defaults to info.par / ptqw.key / seq.par / dam.key if omitted;
    we require the caller to supply the strings explicitly."""

    infoFile: str = "info.par"
    ptqwFile: str = "ptqw.key"
    seqFile: str = "seq.par"
    damFile: str | None = None


class HbvAdapterFiles(FewsModel):
    stateFile: str | None = None
    inputFile: str | None = None
    outputFile: str
    damFlowFile: str | None = None
    outputFileAsBinary: bool | None = None
    diagnosticFile: str | None = None
    hbvInitializationFile: str | None = None
    propertiesFile: HbvModelPropertiesFiles | None = None


class HbvModelFiles(FewsModel):
    hbvInitializationFile: str | None = None
    ptqFile: str | None = None
    damFlowFile: str | None = None
    resFile: str
    logFile: str | None = None
    propertiesFile: HbvModelPropertiesFiles | None = None
    deleteDosptqFile: bool | None = None


class HbvVariables(FewsModel):
    damcheck: HbvVariable | None = None
    automaticCorrection: HbvVariable | None = None


class HbvActionSpecifications(FewsModel):
    action: list[HbvActionSpec] = Field(min_length=1)


class HbvModel(FewsModel):
    """Root of HbvModel.xml."""

    version: str = "1.1"
    description: str | None = None
    directories: HbvFolderNames
    adapterfiles: HbvAdapterFiles
    modelFiles: HbvModelFiles
    variables: HbvVariables | None = None
    actionSpec: HbvActionSpecifications | None = None
