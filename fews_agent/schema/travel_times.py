"""TravelTimes.xml — upstream/downstream travel time relations between stations."""
from __future__ import annotations

from typing import Annotated

from pydantic import Field

from .common import FewsModel, RelativeViewPeriod, UnitMultiplier


class TravelTimeLocation(FewsModel):
    id: str
    name: str | None = None
    parameterId: str | None = None


class CorrelationEquations(FewsModel):
    """XSD CorrelationEquationsComplexType — regression form for the fallback relation."""

    equationType: str  # enum: polynomial | simple_linear | multiple_linear | exponential_* | power | logarithmic | hyperbolic
    polynomialOrder: Annotated[int, Field(ge=1, le=9)] | None = None


class TravelTime(FewsModel):
    downstreamLocation: TravelTimeLocation
    upstreamLocation: list[TravelTimeLocation] = Field(min_length=1)
    travelTime: UnitMultiplier | None = None
    validPeriod: RelativeViewPeriod
    defaultEquation: CorrelationEquations | None = None
    userDefinedRelation: list[str] = Field(default_factory=list)


class TravelTimes(FewsModel):
    """Root of TravelTimes.xml."""

    travelTime: list[TravelTime] = Field(default_factory=list)
