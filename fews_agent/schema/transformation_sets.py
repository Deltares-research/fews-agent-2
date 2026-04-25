"""TransformationSets.xml — pre-process / post-process transformations
applied to time series sets in the region.

Each <transformationSet> wraps one or more inputVariable + an
algorithm choice (arithmetic, hydroMeteo, rule-based, aggregate,
disaggregate, nonequidistantToEquidistant, statistics) + zero or more
outputVariable. The algorithm choice payload is a deeply-nested family
of branches with their own option attributes, so the chosen branch is
passed through as a ``dict[str, Any]`` (single-key dict naming the
branch). The Variable element re-uses ``DataVariable`` from common.py
for full XSD coverage of the timeSeriesSet/defined-data/harmonic
shapes.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from .common import DataVariable, FewsModel


# Algorithm branches modelled as a single-key passthrough dict. Keys
# match the XSD <choice> element names; payload keys follow the @attr
# convention used by `dict_to_xml`.
_ALGORITHM_KEYS = {
    "arithmeticFunction",
    "hydroMeteoFunction",
    "ruleBasedTransformation",
    "aggregate",
    "disaggregate",
    "nonequidistantToEquidistant",
    "statistics",
}


class TransformationSet(FewsModel):
    """XSD TransformationSetComplexType.

    Sequence (XSD-strict): inputVariable[] (>=1), algorithm-choice (one
    of the seven branches, possibly repeated for the unbounded ones),
    then outputVariable[] (>=0).
    """

    inputVariable: list[DataVariable] = Field(min_length=1)
    # Single-key dict: {<branch>: <branch-payload>} or
    # {<branch>: [<branch-payload>, ...]} when the XSD allows
    # maxOccurs="unbounded" on that branch (arithmeticFunction,
    # hydroMeteoFunction).
    algorithm: dict[str, Any] = Field(default_factory=dict)
    outputVariable: list[DataVariable] = Field(default_factory=list)
    transformationId: str | None = None

    @model_validator(mode="after")
    def _algorithm_branch(self) -> "TransformationSet":
        if len(self.algorithm) != 1:
            raise ValueError(
                "TransformationSet.algorithm: supply exactly one branch key"
            )
        (key,) = self.algorithm.keys()
        if key not in _ALGORITHM_KEYS:
            raise ValueError(
                f"TransformationSet.algorithm: unknown branch '{key}'. "
                f"Allowed: {sorted(_ALGORITHM_KEYS)}"
            )
        return self


class TransformationSets(FewsModel):
    """Root of TransformationSets.xml."""

    logLevel: Literal["DEBUG", "INFO", "WARN", "ERROR", "FATAL"] | None = None
    transformationSet: list[TransformationSet] = Field(min_length=1)
