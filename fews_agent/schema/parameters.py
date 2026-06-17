"""Parameters.xml — declares parameterId and parameterGroupId.

The file uses the ``<parameterGroups>`` root element (not
``<parameters>``). The XSD offers two root elements — ``parameters`` and
``parameterGroups`` — sharing most types. Our model covers the
``parameterGroups`` form since that's what real configs use, including
the tutorial.

Each ``<parameterGroup>`` is an XSD choice between:
  - ``enumerationId`` — references a TimeSeriesValueEnumeration
  - an inline block: parameterType + optional dimension + unit +
    optional displayUnit / valueResolution / valueResolutionUnit /
    usesDatum

The enumerationId form is a 2015+ shorthand; the inline form is the
traditional one. Validator enforces exactly one.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from .common import FewsModel
from .enums import ParameterType
from .ids import ParameterGroupId, ParameterId


StandardNameModifier = Literal[
    "detection_minimum", "number_of_observations",
    "standard_error", "status_flag",
]
CellMethod = Literal[
    "point", "sum", "maximum", "median", "mid_range", "minimum",
    "mean", "mode", "standard_deviation", "variance",
]
VerticalPositiveDirection = Literal["up", "down"]


class Dimension(FewsModel):
    """SI dimension exponents (all optional, default 0) — used by
    ParameterGroup.dimension. The XSD doesn't define defaults; callers
    omit exponents that are zero."""

    name: str
    length: int | None = None
    mass: int | None = None
    time: int | None = None
    temperature: int | None = None
    electricCurrent: int | None = None
    amountOfSubstance: int | None = None
    luminousIntensity: int | None = None


class Parameter(FewsModel):
    """XSD ParameterComplexType — shortName is the only required child;
    the rest are optional. standardName / standardNameModifier form an
    optional inner sequence (if present, standardName is required within
    it). standardName uses CF-conventions vocabulary (e.g.
    ``water_surface_height_above_reference_datum``)."""

    id: ParameterId
    shortName: str
    name: str | None = None
    description: str | None = None
    allowedValuesAttributeId: str | None = None
    simulatedHistoricalParameterId: str | None = None
    valueResolution: Decimal | None = None
    valueResolutionUnit: str | None = None
    allowMissing: bool | None = None
    standardName: str | None = None
    standardNameModifier: StandardNameModifier | None = None
    cellMethod: CellMethod | None = None
    verticalPositiveDirection: VerticalPositiveDirection | None = None

    @model_validator(mode="after")
    def _standard_name_sequence(self) -> Parameter:
        if self.standardNameModifier is not None and self.standardName is None:
            raise ValueError(
                "parameter: standardNameModifier requires standardName to be set "
                "(XSD has them in a joined optional sequence)"
            )
        return self


class ParameterGroup(FewsModel):
    """XSD choice: enumerationId (shorthand) XOR the inline sequence
    (parameterType + unit + optional dimension / displayUnit /
    valueResolution / valueResolutionUnit / usesDatum).

    valueResolution uses Decimal to preserve exact source text from JSON
    (e.g. "0.00000000000000000001" must not collapse to "1E-20"). Same
    rationale as schema.locations re: Decimal.
    """

    id: ParameterGroupId
    parameter: list[Parameter] = Field(min_length=1)
    name: str | None = None
    description: str | None = None
    # XSD choice — exactly one of enumerationId form or the inline form
    enumerationId: str | None = None
    parameterType: ParameterType | None = None
    dimension: Dimension | None = None
    unit: str | None = None
    displayUnit: str | None = None
    valueResolution: Decimal | None = None
    valueResolutionUnit: str | None = None
    usesDatum: bool | None = None

    @model_validator(mode="after")
    def _choice(self) -> ParameterGroup:
        has_enum = self.enumerationId is not None
        has_inline = self.parameterType is not None or self.unit is not None
        if has_enum and has_inline:
            raise ValueError(
                "parameterGroup: enumerationId is mutually exclusive with the "
                "inline (parameterType/unit/...) form"
            )
        if not has_enum:
            # Inline form requires both parameterType and unit
            missing = []
            if self.parameterType is None:
                missing.append("parameterType")
            if self.unit is None:
                missing.append("unit")
            if missing:
                raise ValueError(
                    f"parameterGroup: inline form requires {missing} "
                    f"(or supply enumerationId as shorthand)"
                )
        return self


class EnumerationValue(FewsModel):
    """One code/label pair inside a TimeSeriesValueEnumeration."""

    code: str
    label: str
    description: str | None = None


class TimeSeriesValueEnumeration(FewsModel):
    id: str
    value: list[EnumerationValue] = Field(min_length=1)


class TimeSeriesValueEnumerations(FewsModel):
    enumeration: list[TimeSeriesValueEnumeration] = Field(min_length=1)


class Parameters(FewsModel):
    """Root of Parameters.xml — rendered with ``<parameterGroups>`` element
    (FEWS uses the ParameterGroupsComplexType root, not ParametersComplexType).

    ``defaultSpectrumDomainParameterId`` is a rarely-set top-level
    optional used when the domain parameter for a spectrum isn't
    explicitly supplied in a timeSeriesSet.
    """

    parameterGroup: list[ParameterGroup] = Field(min_length=1)
    description: str | None = None
    # UnitConversionSequence (precedes defaultSpectrumDomainParameterId in XSD)
    displayUnitConversionsId: str | None = None
    configUnitConversionsId: str | None = None
    defaultSpectrumDomainParameterId: str | None = None
    # SpecialParametersSequence (between defaultSpectrumDomainParameterId and
    # the parameterGroup list): parameter ids used to resolve special UI axes.
    ratingCurveStageParameterId: ParameterId | None = None
    ratingCurveDischargeParameterId: ParameterId | None = None
    chainageParameterId: ParameterId | None = None
    tideNumberParameterId: ParameterId | None = None
    version: str = "1.0"
