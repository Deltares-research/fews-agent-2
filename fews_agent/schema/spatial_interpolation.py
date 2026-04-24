"""Shared SpatialInterpolationComplexType model.

Lives here because it's the core of ``interpolationSets`` and is embedded
by ``floodMapSets`` (and other files). The XSD type is flat but carries
several enum and small complex sub-types (Variogram, DistanceGeographic,
Debug) — all modelled here as typed Pydantic classes.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import model_validator

from .common import FewsModel


SpatialInterpolationOption = Literal[
    "kriging",
    "bilinear",
    "gridcellaveraging",
    "gridCellAveragingUsingXMLData",
    "inversedistance",
    "closestdistance",
    "sum",
    "average",
    "inputAverageTimesOutputArea",
    "renkaClineTriangulation",
]
InterpolationKind = Literal["seriesfilling", "seriesgeneration"]
InterpolationValuesOption = Literal["normal", "residuals", "splitwithelevation"]
SpatialExtrapolationOption = Literal["disabled", "use splines", "nearest neighbour"]
VariogramType = Literal["spherical", "exponential", "gaussian", "power", "linear"]


class Variogram(FewsModel):
    """XSD choice: slope XOR sill. Slope is for the linear variogram;
    sill is for every other variogram type."""

    type: VariogramType
    nugget: Decimal
    range: Decimal
    slope: Decimal | None = None
    sill: Decimal | None = None

    @model_validator(mode="after")
    def _one_of(self) -> Variogram:
        if (self.slope is None) == (self.sill is None):
            raise ValueError("variogram: supply exactly one of slope / sill")
        return self


class DistanceGeographic(FewsModel):
    """Coefficients G1..G4 of the FEWS DistanceGeographic function."""

    g1: Decimal
    g2: Decimal
    g3: Decimal
    g4: Decimal


class InterpolationDebug(FewsModel):
    level: int
    file: str


class SpatialInterpolation(FewsModel):
    """XSD SpatialInterpolationComplexType — flat settings for one
    spatial interpolation."""

    interpolationOption: SpatialInterpolationOption
    interpolationType: InterpolationKind
    valueOption: InterpolationValuesOption | None = None
    variogram: Variogram | None = None
    numberOfStations: int | None = None
    regressionElevation: Decimal | None = None
    minimumValue: Decimal | None = None
    distanceParameters: DistanceGeographic | None = None
    debug: InterpolationDebug | None = None
    extrapolationOption: SpatialExtrapolationOption | None = None
    coordinateScalingFactor: Decimal | None = None
    coordinateFile: str | None = None
    coordinateSytem: int | None = None  # XSD misspelling preserved
    inversDistancePower: Decimal | None = None  # XSD misspelling preserved
    searchCriteria: int | None = None
    searchRadius: Decimal | None = None
