"""TransformationCoefficientSets.xml — region-config sets of coefficients
keyed by id, optionally further split by period and/or location.

The XSD's CoefficientSetChoiceGroup (adjust / altitude / filter /
generation / lookup / merge / moisture / selection / stageDischarge /
structure / user) is a wide choice over deeply-nested coefficient
sub-shapes. Each branch is its own multi-level tree of typed
sub-elements that adds little value to model field-by-field at this
layer, so the per-set coefficient block is passed through as a
``dict[str, Any]`` (single-key dict naming the chosen branch). The
template emits its keys with ``dict_to_xml``, preserving XSD-sequence
ordering as it appears in the input data.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from .common import FewsModel, Period, SeasonCondition


class PeriodCondition(FewsModel):
    """XSD PeriodConditionComplexType — choice of a literal period
    or a season span.

    Modelled as two optional siblings; exactly one must be supplied.
    Sub-element names in the output XSD: ``period`` and ``season``.
    """

    period: Period | None = None
    season: SeasonCondition | None = None

    @model_validator(mode="after")
    def _one_of(self) -> "PeriodCondition":
        if (self.period is None) == (self.season is None):
            raise ValueError(
                "PeriodCondition: supply exactly one of period or season"
            )
        return self


class LocationCondition(FewsModel):
    """XSD LocationConditionComplexType — locationId (+ optional name)."""

    locationId: str
    locationName: str | None = None


class PeriodDependentCoefficientSet(FewsModel):
    """XSD PeriodDependentCoefficientSetComplexType.

    Sequence: one or more <period> children, then one CoefficientSetChoice
    branch (passthrough dict).
    """

    period: list[PeriodCondition] = Field(min_length=1)
    coefficientSet: dict[str, Any] = Field(default_factory=dict)


class LocationDependentCoefficientSet(FewsModel):
    """XSD LocationDependentCoefficientSetComplexType.

    Sequence: one or more <location> children, then either a
    CoefficientSetChoice branch (passthrough dict in `coefficientSet`)
    OR one or more <periodCoefficientSet> children.
    """

    location: list[LocationCondition] = Field(min_length=1)
    coefficientSet: dict[str, Any] | None = None
    periodCoefficientSet: list[PeriodDependentCoefficientSet] = Field(default_factory=list)

    @model_validator(mode="after")
    def _exactly_one_form(self) -> "LocationDependentCoefficientSet":
        has_set = bool(self.coefficientSet)
        has_period = bool(self.periodCoefficientSet)
        if has_set == has_period:
            raise ValueError(
                "LocationDependentCoefficientSet: supply exactly one of "
                "coefficientSet or periodCoefficientSet"
            )
        return self


class TransformationCoefficientSet(FewsModel):
    """XSD TransformationCoefficientSetComplexType — choice between three
    forms keyed by id."""

    id: str
    coefficientSet: dict[str, Any] | None = None
    periodCoefficientSet: list[PeriodDependentCoefficientSet] = Field(default_factory=list)
    locationCoefficientSet: list[LocationDependentCoefficientSet] = Field(default_factory=list)

    @model_validator(mode="after")
    def _exactly_one_form(self) -> "TransformationCoefficientSet":
        forms = [
            bool(self.coefficientSet),
            bool(self.periodCoefficientSet),
            bool(self.locationCoefficientSet),
        ]
        if sum(forms) != 1:
            raise ValueError(
                "TransformationCoefficientSet: supply exactly one of "
                "coefficientSet / periodCoefficientSet[] / locationCoefficientSet[]"
            )
        return self


class TransformationCoefficientSets(FewsModel):
    """Root of TransformationCoefficientSets.xml."""

    timeZone: str | None = None
    coefficientSet: list[TransformationCoefficientSet] = Field(min_length=1)
