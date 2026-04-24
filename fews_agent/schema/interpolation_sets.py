"""InterpolationSets.xml — legacy interpolation-set definitions.

Fixed ``version="1.1"``. Each ``<interpolationSet>`` carries:

  - an XSD ``choice maxOccurs=unbounded`` over serial/spatial
    interpolation actions (modelled as parallel lists — caller chooses
    ordering at emit time, but XSD accepts any interleaving);
  - an XSD choice over the input/output time-series layout:
    ``timeSeriesSet[]`` (same-as-input) XOR
    (``timeSeriesInputSet[]`` + optional ``timeSeriesOutputSet[]`` XOR
     ``outputSet``).

SpatialInterpolation is shared from ``spatial_interpolation.py``.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from .common import FewsModel, GridDefinition, TimeSeriesSet, UnitMultiplier
from .spatial_interpolation import SpatialInterpolation


SerialInterpolationOption = Literal[
    "defaultvalue", "linear", "block", "extrapolate", "extrapolatetobase",
]
ExtrapolateDirection = Literal["none", "start", "end", "both"]


class SerialInterpolation(FewsModel):
    serialInterpolationOption: SerialInterpolationOption
    gapLength: int | None = None
    defaultValue: Decimal | None = None
    window: UnitMultiplier | None = None
    baseValue: Decimal | None = None
    extrapolateDirection: ExtrapolateDirection | None = None


class InterpolationOutputSet(FewsModel):
    """XSD OutputSetComplexType — timeSeriesOutputSet + optional gridDefinition.
    Flagged obsolete in the XSD — prefer region-level grid definitions."""

    timeSeriesOutputSet: TimeSeriesSet
    gridDefinition: GridDefinition | None = None


class InterpolationSet(FewsModel):
    """Two parallel XSD choices (see module docstring).

    ``serialInterpolation`` / ``spatialInterpolation`` are parallel lists
    — XSD accepts any interleaving within the outer choice.

    For the IO block: either ``timeSeriesSet[]`` (input==output) OR
    ``timeSeriesInputSet[]`` + at most one of
    ``timeSeriesOutputSet[]`` / ``outputSet``.
    """

    interpolationId: str
    serialInterpolation: list[SerialInterpolation] = Field(default_factory=list)
    spatialInterpolation: list[SpatialInterpolation] = Field(default_factory=list)
    timeSeriesSet: list[TimeSeriesSet] = Field(default_factory=list)
    timeSeriesInputSet: list[TimeSeriesSet] = Field(default_factory=list)
    timeSeriesOutputSet: list[TimeSeriesSet] = Field(default_factory=list)
    outputSet: InterpolationOutputSet | None = None

    @model_validator(mode="after")
    def _choices(self) -> InterpolationSet:
        if not (self.serialInterpolation or self.spatialInterpolation):
            raise ValueError(
                "interpolationSet: at least one serialInterpolation or "
                "spatialInterpolation action required"
            )
        same = bool(self.timeSeriesSet)
        split = bool(self.timeSeriesInputSet)
        if same == split:
            raise ValueError(
                "interpolationSet: supply exactly one of timeSeriesSet[] "
                "(same-as-output) or timeSeriesInputSet[] (+ optional output)"
            )
        if same and (self.timeSeriesOutputSet or self.outputSet is not None):
            raise ValueError(
                "interpolationSet: timeSeriesOutputSet / outputSet only valid "
                "alongside timeSeriesInputSet[]"
            )
        if self.timeSeriesOutputSet and self.outputSet is not None:
            raise ValueError(
                "interpolationSet: timeSeriesOutputSet[] and outputSet are "
                "mutually exclusive"
            )
        return self


class PointPosition(FewsModel):
    """Grid row/col coordinates (attribute-only)."""

    col: int
    row: int


class Basin(FewsModel):
    locationId: str
    cellPoints: list[PointPosition] = Field(min_length=1)
    name: str | None = None


class BasinGroup(FewsModel):
    gridLocationId: str
    basin: list[Basin] = Field(min_length=1)
    description: str | None = None


class InterpolationSets(FewsModel):
    interpolationSet: list[InterpolationSet] = Field(min_length=1)
    basinGroup: list[BasinGroup] = Field(default_factory=list)
    version: Literal["1.1"] = "1.1"
