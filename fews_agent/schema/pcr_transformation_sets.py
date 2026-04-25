"""PcrTransformationSets.xml — PCRaster transformations driven by an
inline PCRaster script text.

Each ``<pcrTransformationSet>`` binds an area-map definition (grid def,
location id, or time-series grid) to a pool of input/output/internal
variables used by the embedded PCRaster script.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import FewsModel, GridDefinition, TimeSeriesSet


LogLevel = Literal["DEBUG", "INFO", "WARN", "ERROR", "FATAL"]
PcrDataExchange = Literal["memory", "file"]
PcrDataType = Literal["boolean", "nominal", "ordinal", "scalar", "ldd", "directional"]
PcrScalarDataType = Literal[
    "timeInJulian", "timeAsDayofYear", "timeAsDayofMonth",
    "timeAsHourofDay", "timeAsDaysElapsedSince", "timeAsHoursElapsedSince",
]
PcrSpatial = Literal["spatial", "nonspatial"]


class PcrAreaMap(FewsModel):
    """XSD choice: gridDefinition XOR locationId XOR timeSeriesSet."""

    gridDefinition: GridDefinition | None = None
    locationId: str | None = None
    timeSeriesSet: TimeSeriesSet | None = None

    @model_validator(mode="after")
    def _one_form(self) -> PcrAreaMap:
        forms = [self.gridDefinition, self.locationId, self.timeSeriesSet]
        if sum(f is not None for f in forms) != 1:
            raise ValueError(
                "pcrAreaMap: supply exactly one of gridDefinition, locationId, "
                "or timeSeriesSet"
            )
        return self


class PcrInternalVariable(FewsModel):
    """Attribute-only element — no time-series binding."""

    variableId: str
    dataType: PcrDataType | None = None


class PcrInputVariable(FewsModel):
    """XSD choice: timeSeriesSet XOR value (constant) XOR external (file)."""

    variableId: str
    dataType: PcrDataType | None = None
    scalarType: PcrScalarDataType | None = None
    convertDatum: bool | None = None
    referenceDate: str | None = None
    spatialType: PcrSpatial | None = None
    timeSeriesSet: TimeSeriesSet | None = None
    value: float | None = None
    external: str | None = None

    @model_validator(mode="after")
    def _one_source(self) -> PcrInputVariable:
        forms = [self.timeSeriesSet, self.value, self.external]
        if sum(f is not None for f in forms) != 1:
            raise ValueError(
                "pcrInputVariable: supply exactly one of timeSeriesSet, value, "
                "or external"
            )
        return self


class PcrOutputVariable(FewsModel):
    variableId: str
    timeSeriesSet: TimeSeriesSet
    dataType: PcrDataType | None = None
    convertDatum: bool | None = None


class PcrDefinitions(FewsModel):
    inputVariable: list[PcrInputVariable] = Field(min_length=1)
    outputVariable: list[PcrOutputVariable] = Field(min_length=1)
    dataExchange: PcrDataExchange | None = None
    internalVariable: list[PcrInternalVariable] = Field(default_factory=list)


class PcrScriptTextModel(FewsModel):
    """Raw PCRaster script text; ``$timesteps$``-style placeholders are
    substituted by FEWS at runtime."""

    text: str
    id: str | None = None


class PcrTransformationSet(FewsModel):
    areaMap: PcrAreaMap
    definitions: PcrDefinitions
    pcrModel: PcrScriptTextModel
    id: str | None = None


class PcrTransformationSets(FewsModel):
    version: str = "1.1"
    logLevel: LogLevel | None = None
    pcrTransformationSet: list[PcrTransformationSet] = Field(min_length=1)
