"""Scenarios.xml — named what-if scenarios with variable transformations."""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field

from .common import DataVariable, FewsModel


class ScenarioVariable(FewsModel):
    variable: DataVariable
    transformationType: Literal[
        "equal",
        "linearwithstartvalueandendvalue",
        "linearwithstartvalueandincrement",
    ]
    defaultValue: list[Decimal] = Field(min_length=1)


class Scenario(FewsModel):
    name: str
    id: str | None = None
    description: str | None = None
    scenarioVariable: list[ScenarioVariable] = Field(min_length=1)


class Scenarios(FewsModel):
    """Root of Scenarios.xml."""

    description: str | None = None
    scenario: list[Scenario] = Field(min_length=1)
    version: str = "1.1"
