"""Delft3DModel.xml — Delft3D model adapter config.

Three sections:
  - general: common files + module id + run id
  - preAdapter: input-prep settings
  - postAdapter: output time-series / map-stack mappings
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import FewsModel, GridDefinition, TimeZone


Delft3DModule = Literal["FLOW", "FLOW_FM", "WAQ", "ECO", "WAVE", "PART"]
MapFileFormat = Literal["binary", "NEFIS"]


class Delft3DGeneral(FewsModel):
    """XSD has a choice between `geoDatum` and `gridDefinition` (optional)."""

    module: Delft3DModule
    runId: str
    stateFileId: str | None = None
    workDir: str
    modelDir: str
    auxiliaryGridFile: str | None = None
    fieldFileFormat: str | None = None
    outputTimeSeriesInOneFile: bool | None = None
    geoDatum: str | None = None
    gridDefinition: GridDefinition | None = None
    timeZone: TimeZone | None = None
    online: Literal["MORPHOLOGY"] | None = None
    rstNcFileSubcript: str | None = None
    warnAboutUnusedSeries: bool | None = None

    @model_validator(mode="after")
    def _geo_xor_grid(self) -> Delft3DGeneral:
        if self.geoDatum is not None and self.gridDefinition is not None:
            raise ValueError(
                "delft3dModel.general: set geoDatum OR gridDefinition, not both"
            )
        return self


class Delft3DPreAdapter(FewsModel):
    steeringTimeSeriesName: str
    initialConditionsId: str | None = None
    useWaqMapFilesForInitialConditions: bool | None = None
    runCommand: list[str] = Field(default_factory=list)


class Delft3DTimeSeries(FewsModel):
    parameter: str
    location: str
    layer: int
    fewsParameter: str
    fewsLocation: str


class Delft3DTimeSeriesOutput(FewsModel):
    timeSeries: list[Delft3DTimeSeries] = Field(default_factory=list)


class Delft3DMapStack(FewsModel):
    parameter: str
    layer: int
    fewsParameter: str
    fewsLocation: str


class Delft3DMapStackOutput(FewsModel):
    formatForPart: MapFileFormat | None = None
    map: list[Delft3DMapStack] = Field(default_factory=list)


class Delft3DPostAdapter(FewsModel):
    timeSeriesOutput: Delft3DTimeSeriesOutput | None = None
    mapOutput: Delft3DMapStackOutput | None = None
    runCommand: list[str] = Field(default_factory=list)
    invertTimeStamp: bool | None = None


class Delft3DModel(FewsModel):
    description: str | None = None
    general: Delft3DGeneral
    preAdapter: Delft3DPreAdapter | None = None
    postAdapter: Delft3DPostAdapter | None = None
