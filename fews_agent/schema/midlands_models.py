"""MidlandsModels.xml — legacy Midlands-regional model adapter.

XSD choice at the root: ``<mcrm>`` (catchment runoff model) XOR
``<dodo>`` (river routing model). Both share directory / file-name /
variable blocks from ``midlandsSharedTypes.xsd``.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from .common import FewsModel, TimeStep


InflowLocation = Literal["upstream", "downstream", "lateral"]
InflowType = Literal["catchment", "reach"]


class MidlandsFolderNames(FewsModel):
    configDir: str
    workDir: str
    moduleDir: str
    importDir: str
    exportDir: str


class MidlandsModuleFileNames(FewsModel):
    structureFile: str | None = None
    dataFile: str | None = None
    parameterFile: str | None = None
    inputHindcastFile: str | None = None
    inputForecastFile: str | None = None
    outputHindcastFile: str | None = None
    outputForecastFile: str | None = None
    logFile: str | None = None


class MidlandsAdapterFileNames(FewsModel):
    stateFile: str | None = None
    stateTimeSeriesFile: str | None = None
    parameterFile: str | None = None
    inputHindcastFile: str | None = None
    inputForecastFile: str | None = None
    outputHindcastFile: str | None = None
    outputForecastFile: str | None = None
    diagnosticFile: str | None = None
    inflowHindcastFile: list[str] = Field(default_factory=list, max_length=6)
    inflowForecastFile: list[str] = Field(default_factory=list, max_length=6)


class MidlandsVariables(FewsModel):
    name: str
    reservoir: bool
    useError: bool
    reservoirId: str | None = None
    area: Decimal | None = None
    outputTimeStep: TimeStep | None = None


class MidlandsInflow(FewsModel):
    """Inflow proportion is an XSD float restricted to [0, 100]."""

    name: str
    location: InflowLocation
    type: InflowType
    hindcastFile: str
    forecastFile: str
    proportion: Decimal = Field(ge=0, le=100)


# ── MCRM ───────────────────────────────────────────────────────────────

class McrmInputHindcastParameters(FewsModel):
    discharge: str
    precipitation: str
    temperature: str
    evaporation: str
    reservoirLevel: str | None = None


class McrmInputForecastParameters(FewsModel):
    precipitation: str
    temperature: str
    evaporation: str


class McrmInputParameters(FewsModel):
    hindcastParameters: McrmInputHindcastParameters
    forecastParameters: McrmInputForecastParameters


class McrmOutputHindcastParameters(FewsModel):
    simulatedDischarge: str
    updatedDischarge: str
    soilMoistureDeficit: str
    groundWater: str
    snowWaterEquivalent: str
    snowDensity: str
    reservoirStorage: str | None = None
    reservoirRelease: str | None = None


class McrmOutputForecastParameters(FewsModel):
    simulatedDischarge: str
    updatedDischarge: str
    soilMoistureDeficit: str
    groundWater: str
    snowWaterEquivalent: str
    snowDensity: str
    reservoirStorage: str | None = None
    reservoirRelease: str | None = None


class McrmOutputParameters(FewsModel):
    hindcastParameters: McrmOutputHindcastParameters
    forecastParameters: McrmOutputForecastParameters


class McrmParameters(FewsModel):
    inputParameters: McrmInputParameters
    outputParameters: McrmOutputParameters


class McrmStateParameters(FewsModel):
    snowpackWaterEquivalent: str | None = None
    snowpackDensity: str | None = None
    snowpackDepth: str | None = None
    interceptionStorage: str | None = None
    soilMoistureDeficit: str | None = None
    groundWaterStorage: str | None = None
    reservoirStorage: str | None = None
    reservoirRelease: str | None = None
    channelStorage: str | None = None
    floodplainStorage: str | None = None


class Mcrm(FewsModel):
    directories: MidlandsFolderNames
    adapterfiles: MidlandsAdapterFileNames
    modulefiles: MidlandsModuleFileNames
    variables: MidlandsVariables
    parameters: McrmParameters
    stateParameters: McrmStateParameters | None = None


# ── DODO ───────────────────────────────────────────────────────────────

class DodoInputHindcastParameters(FewsModel):
    discharge: str
    inflowDischarge: list[str] = Field(default_factory=list, max_length=6)


class DodoInputForecastParameters(FewsModel):
    inflowDischarge: list[str] = Field(default_factory=list, max_length=6)


class DodoInputParameters(FewsModel):
    hindcastParameters: DodoInputHindcastParameters
    forecastParameters: DodoInputForecastParameters


class DodoOutputHindcastParameters(FewsModel):
    simulatedDischarge: str
    updatedDischarge: str
    floodPlainStorage: str


class DodoOutputForecastParameters(FewsModel):
    simulatedDischarge: str
    updatedDischarge: str
    floodPlainStorage: str


class DodoOutputParameters(FewsModel):
    hindcastParameters: DodoOutputHindcastParameters
    forecastParameters: DodoOutputForecastParameters


class DodoParameters(FewsModel):
    inputParameters: DodoInputParameters
    outputParameters: DodoOutputParameters


class DodoStateParameters(FewsModel):
    channelStorage: str | None = None
    floodplainStorage: str | None = None
    staticStorageVolume: str | None = None
    staticStorageSwitch: str | None = None
    currentExcessOutflow: str | None = None
    priorExcessOutflow: str | None = None
    lastLaggedOutflow: str | None = None


class Dodo(FewsModel):
    directories: MidlandsFolderNames
    adapterfiles: MidlandsAdapterFileNames
    modulefiles: MidlandsModuleFileNames
    variables: MidlandsVariables
    parameters: DodoParameters
    inflows: list[MidlandsInflow] = Field(min_length=1, max_length=6)
    stateParameters: DodoStateParameters | None = None


# ── Root ───────────────────────────────────────────────────────────────

class MidlandsModel(FewsModel):
    """XSD choice — exactly one of mcrm / dodo."""

    mcrm: Mcrm | None = None
    dodo: Dodo | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> MidlandsModel:
        if (self.mcrm is None) == (self.dodo is None):
            raise ValueError("midlandsModel: supply exactly one of mcrm / dodo")
        return self
