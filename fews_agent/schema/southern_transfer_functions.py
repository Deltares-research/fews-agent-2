"""SouthernTransferFunctions.xml — STF hydrological adapter config.

All-flat shape: directories + files + arguments. No external types
beyond sharedTypes.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel


class SouthernTransferFunctionsFolderNames(FewsModel):
    configDir: str
    workDir: str
    moduleDir: str
    importDir: str
    exportDir: str


class SouthernTransferFunctionsFileNames(FewsModel):
    configCsvFile: str
    parameterCsvFile: str
    ratingsCsvFile: str | None = None
    inputInpFile: str
    outputOutFile: list[str] = Field(min_length=1, max_length=2)
    inputXmlFile: str
    outputXmlFile: str
    diagnosticFile: str
    stfLogFile: str


class SouthernTransferFunctionsArgument(FewsModel):
    outputLocationId1: str
    outputForecastParameterId1: str
    outputHistoricParameterId1: str
    outputDataType1: Literal["accumulative", "instantaneous"]
    outputLocationId2: str | None = None
    inputForecastParameterId1: str | None = None
    inputHistoricParameterId1: str | None = None
    outputForecastParameterId2: str | None = None
    outputHistoricParameterId2: str | None = None
    outputDataType2: Literal["accumulative", "instantaneous"] | None = None


class SouthernTransferFunctions(FewsModel):
    """Root of SouthernTransferFunctions.xml."""

    directories: SouthernTransferFunctionsFolderNames
    files: SouthernTransferFunctionsFileNames
    arguments: SouthernTransferFunctionsArgument
