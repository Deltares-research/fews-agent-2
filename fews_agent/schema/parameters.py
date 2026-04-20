"""Parameters.xml — declares parameterId and parameterGroupId."""
from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from .common import FewsModel
from .enums import ParameterType
from .ids import ParameterGroupId, ParameterId


class Parameter(FewsModel):
    id: ParameterId
    name: str | None = None
    shortName: str | None = None
    description: str | None = None
    standardUnit: str | None = None


class ParameterGroup(FewsModel):
    # valueResolution uses Decimal to preserve the exact source text from
    # JSON (e.g. "0.00000000000000000001" must not collapse to "1E-20").
    # See comment in schema.locations re: Decimal.
    id: ParameterGroupId
    parameterType: ParameterType
    unit: str
    name: str | None = None
    valueResolution: Decimal | None = None
    usesDatum: bool = False
    parameter: list[Parameter] = Field(min_length=1)


class Parameters(FewsModel):
    """Root of Parameters.xml."""

    parameterGroup: list[ParameterGroup] = Field(min_length=1)
    version: str = "1.0"
