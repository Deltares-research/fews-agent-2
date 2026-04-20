"""Parameters.xml — declares parameterId and parameterGroupId."""
from __future__ import annotations

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
    id: ParameterGroupId
    parameterType: ParameterType
    unit: str
    name: str | None = None
    valueResolution: float | None = None
    usesDatum: bool = False
    parameter: list[Parameter] = Field(min_length=1)


class Parameters(FewsModel):
    """Root of Parameters.xml."""

    parameterGroup: list[ParameterGroup] = Field(min_length=1)
    version: str = "1.0"
