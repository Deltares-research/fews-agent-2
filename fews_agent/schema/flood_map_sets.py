"""FloodMapSets.xml — flood extent / longitudinal-profile map builders.

Fixed ``version="1.1"``. Each ``<floodMapSet>`` is an XSD choice between
three kinds:

  - ``longitudinalProfile`` — straightforward file triple.
  - ``floodExtentMap`` — one Input + SpatialInterpolation + optional
    PcrScript + one-or-more Outputs.
  - ``floodMap`` — one or more DEM-based maps (Input + extrapolation +
    single Output each).

``Input`` carries two XSD choices: ``profileFile`` XOR ``timeSeriesFile``,
and ``xmlAxisFile`` XOR ``asciiAxisFile``.

``PcrScript`` has an XSD choice ``pcrScriptFile`` XOR ``pcrScriptXMLFile``.
Other pcrScript fields (pcrExecutableFilename / pcrDllFileName /
pcrArguments) are flagged ``THIS FEATURE NOT SUPPORTED`` in the XSD
but kept for completeness.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import FewsModel
from .spatial_interpolation import SpatialInterpolation


FloodMapOutputOption = Literal["maximumextent", "pertime", "contour"]


class FloodMapDirectories(FewsModel):
    outputDir: str
    inputDir: str
    rootDir: str | None = None
    workDir: str | None = None
    pcrDir: str | None = None


class LongitudinalProfile(FewsModel):
    """XSD uses ``<all>`` so ordering is irrelevant — three required files."""

    branchFile: str
    timeSeriesFile: str
    profileFile: str


class FloodMapInput(FewsModel):
    """Two XSD choices: profileFile XOR timeSeriesFile, and
    xmlAxisFile XOR asciiAxisFile. Both enforced below."""

    asciiDemFile: str
    asciiMapSectionFile: str
    geoReferenceFile: str
    profileFile: str | None = None
    timeSeriesFile: str | None = None
    xmlAxisFile: str | None = None
    asciiAxisFile: str | None = None
    xmlInterpolationOutlineFile: str | None = None
    locationId: str | None = None
    parameterId: str | None = None

    @model_validator(mode="after")
    def _choices(self) -> FloodMapInput:
        if (self.profileFile is None) == (self.timeSeriesFile is None):
            raise ValueError(
                "floodMap input: supply exactly one of profileFile / timeSeriesFile"
            )
        if (self.xmlAxisFile is None) == (self.asciiAxisFile is None):
            raise ValueError(
                "floodMap input: supply exactly one of xmlAxisFile / asciiAxisFile"
            )
        return self


class GridFileOutput(FewsModel):
    filename: str
    mapStackFilename: str | None = None


class ContourOutput(FewsModel):
    filename: str
    numberofContours: int


class FloodMapOutput(FewsModel):
    outputOption: FloodMapOutputOption
    levelOutput: bool | None = None
    asciiGrid: GridFileOutput | None = None
    pcrGrid: GridFileOutput | None = None
    contour: ContourOutput | None = None
    bilGrid: GridFileOutput | None = None


class PcrScript(FewsModel):
    """XSD choice: pcrScriptFile XOR pcrScriptXMLFile."""

    pcrExecutableFilename: str | None = None
    pcrDllFileName: str | None = None
    pcrScriptFile: str | None = None
    pcrScriptXMLFile: str | None = None
    pcrArguments: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_script(self) -> PcrScript:
        if (self.pcrScriptFile is None) == (self.pcrScriptXMLFile is None):
            raise ValueError(
                "pcrScript: supply exactly one of pcrScriptFile / pcrScriptXMLFile"
            )
        return self


class FloodExtentMap(FewsModel):
    input: FloodMapInput
    interpolationOptions: SpatialInterpolation
    output: list[FloodMapOutput] = Field(min_length=1)
    pcrScript: PcrScript | None = None


class FloodExtrapolation(FewsModel):
    extrapolationSteps: int | None = None
    cleanUpProfile: bool | None = None


class FloodDemMap(FewsModel):
    input: FloodMapInput
    extrapolationOptions: FloodExtrapolation
    output: FloodMapOutput


class FloodMapSet(FewsModel):
    """XSD choice: longitudinalProfile XOR floodExtentMap XOR floodMap[].
    Exactly one branch must be set."""

    longitudinalProfile: LongitudinalProfile | None = None
    floodExtentMap: FloodExtentMap | None = None
    floodMap: list[FloodDemMap] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_kind(self) -> FloodMapSet:
        branches = [
            self.longitudinalProfile is not None,
            self.floodExtentMap is not None,
            bool(self.floodMap),
        ]
        if sum(branches) != 1:
            raise ValueError(
                "floodMapSet: supply exactly one of longitudinalProfile / "
                "floodExtentMap / floodMap[]"
            )
        return self


class FloodMapSets(FewsModel):
    floodMapDirectories: FloodMapDirectories
    floodMapSet: list[FloodMapSet] = Field(min_length=1)
    description: str | None = None
    geoDatum: str | None = None
    diagnosticFile: str | None = None
    version: Literal["1.1"] = "1.1"
