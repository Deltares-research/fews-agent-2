"""RatingCurves.xml — stage-discharge (level↔flow) relations per location.

Each ``<ratingCurve>`` can carry:
  - a ``<ratingCurveTable>`` with (level, flow) tuples, OR
  - one or more parametric ``<ratingCurveEquation>`` segments (pre-defined
    Power / Parabolic equation with a/b/c, or a user-defined function),
  - optionally a ``<correction>`` block (Jones unsteady-flow equation
    and/or constant- or normal-fall backwater correction).
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import FewsModel, ValidPeriod


RatingCurveType = Literal["LevelToFlow", "FlowToLevel"]
EquationType = Literal["Power", "Parabolic"]


class RatingCurveLocation(FewsModel):
    locationId: str
    name: str | None = None


class JonesEquation(FewsModel):
    h_min: float
    a: float
    b: float
    c: float


class UnsteadyFlowCorrection(FewsModel):
    jonesEquation: JonesEquation


class ConstantFallMethod(FewsModel):
    referenceFall: float


class NormalFallMethod(FewsModel):
    h_min: float
    a: float
    b: float
    c: float


class BackWaterCorrection(FewsModel):
    """XSD choice: constantFallMethod XOR normalFallMethod."""

    referenceLocation: RatingCurveLocation
    constantFallMethod: ConstantFallMethod | None = None
    normalFallMethod: NormalFallMethod | None = None

    @model_validator(mode="after")
    def _one_method(self) -> BackWaterCorrection:
        if (self.constantFallMethod is None) == (self.normalFallMethod is None):
            raise ValueError(
                "backwater: supply exactly one of constantFallMethod or normalFallMethod"
            )
        return self


class RatingCurveCorrection(FewsModel):
    unsteadyFlow: UnsteadyFlowCorrection | None = None
    backwater: BackWaterCorrection | None = None


class RatingCurveTableRecord(FewsModel):
    level: float
    flow: float


class RatingCurveTable(FewsModel):
    ratingCurveTableRecord: list[RatingCurveTableRecord] = Field(min_length=1)


class RatingCurveEquationCoefficient(FewsModel):
    id: str
    value: float


class RatingCurveEquation(FewsModel):
    """XSD choice at tail: (equation + a + b + c) pre-defined form XOR
    userDefinedEquation-based form (with optional reverse equation and
    free-form coefficients)."""

    lowerLevel: float | None = None
    upperLevel: float | None = None
    flag: int | None = None
    # pre-defined branch
    equation: EquationType | None = None
    a: float | None = None
    b: float | None = None
    c: float | None = None
    # user-defined branch
    userDefinedEquation: str | None = None
    inputVariable: str | None = None
    reverseUserDefinedEquation: str | None = None
    reverseEquationInputVariable: str | None = None
    coefficient: list[RatingCurveEquationCoefficient] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_branch(self) -> RatingCurveEquation:
        predef = (self.equation, self.a, self.b, self.c)
        has_predef = any(v is not None for v in predef)
        has_user = self.userDefinedEquation is not None
        if has_predef and has_user:
            raise ValueError(
                "ratingCurveEquation: pre-defined (equation/a/b/c) and user-defined "
                "forms are mutually exclusive"
            )
        if has_predef and not all(v is not None for v in predef):
            raise ValueError(
                "ratingCurveEquation: pre-defined form requires all of "
                "equation/a/b/c"
            )
        if not has_predef and not has_user:
            raise ValueError(
                "ratingCurveEquation: supply either pre-defined (equation+a+b+c) "
                "or userDefinedEquation"
            )
        return self


class RatingCurve(FewsModel):
    ratingCurveId: str | None = None
    description: str | None = None
    location: RatingCurveLocation
    ratingCurveType: RatingCurveType
    reversible: bool | None = None
    validPeriod: list[ValidPeriod] = Field(default_factory=list)
    correction: RatingCurveCorrection | None = None
    ratingCurveTable: RatingCurveTable | None = None
    ratingCurveEquation: list[RatingCurveEquation] = Field(default_factory=list)


class RatingCurves(FewsModel):
    version: str = "1.1"
    ratingCurve: list[RatingCurve] = Field(min_length=1)
