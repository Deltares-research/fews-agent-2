"""Barriers.xml — barrier state definitions for the decision module.

Works in tandem with ``DecisionModule``: each barrier here defines the
state variables and transitions that the decision tree picks between.

The XSD spells ``stateDefnitionId`` (sic) — preserved here so the
generator round-trips the typo for byte-identical XML.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel
from .decision_module import DecisionVariableDefinition


class StateVariable(FewsModel):
    """Inner element of ``<stateVariables>``."""

    id: str
    variableId: str


class StateVariables(FewsModel):
    stateVariable: list[StateVariable] = Field(min_length=1)


class StateVariableValue(FewsModel):
    """Attribute-only element — ``stateVariableId`` + numeric ``value``."""

    stateVariableId: str
    value: float


class BarrierStateValue(FewsModel):
    id: str
    value: str
    stateVariableValue: list[StateVariableValue] = Field(min_length=1)


class ParameterValue(FewsModel):
    parameterId: str
    value: float


class TransitionTimeOffset(FewsModel):
    unit: str
    value: int


class TransitionLevelSpeed(FewsModel):
    """simpleContent extension of string with ``level`` + ``speed`` attrs."""

    body: str
    level: float
    speed: float


class TransitionValue(FewsModel):
    """XSD choice: value[] (level/speed simpleContent) XOR constantValue
    (plain float)."""

    stateVariableId: str
    timeOffset: TransitionTimeOffset | None = None
    value: list[TransitionLevelSpeed] = Field(default_factory=list)
    constantValue: float | None = None

    @model_validator(mode="after")
    def _one_branch(self) -> TransitionValue:
        has_values = bool(self.value)
        has_const = self.constantValue is not None
        if has_values == has_const:
            raise ValueError(
                "transitionValue: supply exactly one of value[] or constantValue"
            )
        return self


class BarrierStateTransition(FewsModel):
    startStateValueId: str
    endStateValueId: str
    transitionValue: list[TransitionValue] = Field(min_length=1)


class Transitions(FewsModel):
    stateTransition: list[BarrierStateTransition] = Field(min_length=1)


class BarrierStateDefinition(FewsModel):
    id: str
    variableId: str
    stateVariables: StateVariables
    stateValue: list[BarrierStateValue] = Field(min_length=1)
    transitions: Transitions


class Barrier(FewsModel):
    id: str
    name: str
    stateDefinition: list[BarrierStateDefinition] = Field(min_length=1)


class Barriers(FewsModel):
    variable: list[DecisionVariableDefinition] = Field(min_length=1)
    barrier: list[Barrier] = Field(min_length=1)
