"""PrtfDisplay.xml — PRTF model display and parameter-editing config.

Each ``<prtfGroup>`` binds a workflow + module instance to an optional
location / locationSet selection, optional sub-groups, and the parameter
definitions used by PRTF.

``ParameterData`` is an XSD choice with simpleContent-extension variants
(bool / double / int with attrs) and a plain ``stringData`` string
element. Modelled as four optional fields + a validator.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import DataVariable, FewsModel


LineStyle = Literal[
    "none", "solid", "dashed", "dotted", "dashdot", "dashdotdot",
    "thickSolid", "thickDashed", "thickDotted", "thickDashdot",
    "thickDashdotdot",
]  # chartLineStyleEnumStringType — we let XSD enforce the exact set
MarkerStyle = str  # markerStyleEnumStringType — many values, let XSD check


class DisplayOptions(FewsModel):
    """sharedTypes DisplayOptionsComplexType — chart line/marker style."""

    key: str | None = None
    preferredColor: str | None = None
    lineStyle: str | None = None
    markerStyle: str | None = None
    markerSize: int | None = None
    markerFilled: bool | None = None


class BooleanData(FewsModel):
    """simpleContent extension of boolean with ``allowAdjust`` attr."""

    value: bool
    allowAdjust: bool | None = None


class DoubleData(FewsModel):
    """simpleContent extension of double with min/max + optional attrs."""

    value: float
    maxVal: float
    minVal: float
    allowAdjust: bool | None = None
    stepSize: float | None = None


class IntData(FewsModel):
    value: int
    maxVal: int
    minVal: int
    allowAdjust: bool | None = None
    stepSize: int | None = None


class ParameterData(FewsModel):
    """XSD choice — exactly one of booleanData / doubleData / intData /
    stringData (plain string)."""

    booleanData: BooleanData | None = None
    doubleData: DoubleData | None = None
    intData: IntData | None = None
    stringData: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> ParameterData:
        forms = [
            self.booleanData, self.doubleData, self.intData, self.stringData,
        ]
        if sum(f is not None for f in forms) != 1:
            raise ValueError(
                "ParameterData: supply exactly one of booleanData / doubleData "
                "/ intData / stringData"
            )
        return self


class PRTFItem(FewsModel):
    key: str
    data: ParameterData | None = None
    description: str | None = None


class PRTFParameter(FewsModel):
    name: str
    item: list[PRTFItem] = Field(min_length=1)
    default: int | None = None


class PRTFSubGroup(FewsModel):
    """XSD choice: locationId[] XOR locationSetId (single)."""

    name: str
    locationId: list[str] = Field(default_factory=list)
    locationSetId: str | None = None

    @model_validator(mode="after")
    def _one_form(self) -> PRTFSubGroup:
        has_loc = bool(self.locationId)
        has_set = self.locationSetId is not None
        if has_loc == has_set:
            raise ValueError(
                "prtfSubGroup: supply exactly one of locationId[] or locationSetId"
            )
        return self


class PRTFGroupOptions(FewsModel):
    groupParameter: list[PRTFParameter] = Field(default_factory=list)


class PRTFGroup(FewsModel):
    """XSD optional choice: locationId[] XOR locationSetId (neither is OK)."""

    workflowId: str
    moduleInstanceId: str
    groupOptions: PRTFGroupOptions
    name: str | None = None
    locationId: list[str] = Field(default_factory=list)
    locationSetId: str | None = None
    subGroup: list[PRTFSubGroup] = Field(default_factory=list)
    approvedWorkflowId: str | None = None

    @model_validator(mode="after")
    def _loc_choice(self) -> PRTFGroup:
        if self.locationId and self.locationSetId is not None:
            raise ValueError(
                "prtfGroup: locationId[] and locationSetId are mutually exclusive"
            )
        return self


class PRTFDisplay(FewsModel):
    title: str
    inputVariable: list[DataVariable] = Field(min_length=1)
    prtfGroup: list[PRTFGroup] = Field(min_length=1)
    outputVariable: list[DataVariable] = Field(min_length=1)
    idMapId: str | None = None
    scenarioIdMapId: str | None = None
    globalParameter: list[PRTFParameter] = Field(default_factory=list)
    displayOptions: list[DisplayOptions] = Field(default_factory=list)
