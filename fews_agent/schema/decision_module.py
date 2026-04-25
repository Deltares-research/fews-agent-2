"""DecisionModule.xml — barrier decision-tree configuration.

Reuses ``CriticalConditionLookup`` and ``RuleCriterias`` from
``lookup_sets`` — those are the same XSD types, pulled in via XSD
``include``.

``RuleConstraint`` is recursive (``not``, ``anyValid``, ``allValid``
wrap further constraints) — modelled with a self-referential
``model_rebuild()`` + the usual seven-choice validator.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import FewsModel, TimeSeriesSet
from .lookup_sets import CriticalConditionLookup, RuleCriterias


RuleType = Literal["RelativeToCriticalCondition", "OnCriticalCondition"]
TimeUnit = Literal["second", "minute", "hour", "day"]
StateChangeEvaluationType = Literal["FirstInTime", "All"]
DecisionEvaluationType = Literal["lastKnownState"]


class DecisionVariableDefinition(FewsModel):
    variableId: str
    timeSeriesSet: TimeSeriesSet


class TimeOffset(FewsModel):
    unit: TimeUnit
    value: int


class TransitionRule(FewsModel):
    """XSD choice: criticalConditionName XOR transitionRuleId."""

    id: str
    ruleType: RuleType
    criticalConditionName: str | None = None
    transitionRuleId: str | None = None
    transitionCondition: RuleCriterias | None = None
    timeOffset: TimeOffset | None = None

    @model_validator(mode="after")
    def _one_ref(self) -> TransitionRule:
        if (self.criticalConditionName is None) == (self.transitionRuleId is None):
            raise ValueError(
                "transitionRule: supply exactly one of criticalConditionName or "
                "transitionRuleId"
            )
        return self


class TransitionRules(FewsModel):
    transitionRule: list[TransitionRule] = Field(min_length=1)


class Rules(FewsModel):
    variable: list[DecisionVariableDefinition] = Field(min_length=1)
    criticalConditions: CriticalConditionLookup
    transitionRules: TransitionRules


class RuleConstraints(FewsModel):
    """Unbounded list of RuleConstraint choice items."""

    ruleConstraint: list["RuleConstraint"] = Field(min_length=1)


class RuleConstraint(FewsModel):
    """XSD choice: not (nested RuleConstraint) / anyValid / allValid
    (RuleConstraints) / alwaysTrue / alwaysFalse / isTrue / isFalse (ruleId)."""

    not_: "RuleConstraint | None" = Field(default=None, alias="not")
    anyValid: RuleConstraints | None = None
    allValid: RuleConstraints | None = None
    alwaysTrue: str | None = None
    alwaysFalse: str | None = None
    isTrue: str | None = None
    isFalse: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> RuleConstraint:
        forms = [
            self.not_, self.anyValid, self.allValid,
            self.alwaysTrue, self.alwaysFalse, self.isTrue, self.isFalse,
        ]
        if sum(f is not None for f in forms) != 1:
            raise ValueError(
                "ruleConstraint: supply exactly one of not / anyValid / allValid / "
                "alwaysTrue / alwaysFalse / isTrue / isFalse"
            )
        return self


# Resolve forward reference
RuleConstraints.model_rebuild()


class DecisionStates(FewsModel):
    stateValueId: str


class Decision(FewsModel):
    id: str
    stateDefinitionId: str
    inputState: DecisionStates
    conditionRules: RuleConstraints
    transitionRules: RuleConstraints
    outputState: DecisionStates
    evaluationType: DecisionEvaluationType | None = None


class DecisionTree(FewsModel):
    barrierId: str
    decision: list[Decision] = Field(min_length=1)


class DecisionInitialConditionalWorkflow(FewsModel):
    variableId: list[str] = Field(min_length=1)
    workflowId: str


class DecisionStateChange(FewsModel):
    decisionTreeId: str


class StateChanges(FewsModel):
    stateChange: list[DecisionStateChange] = Field(min_length=1)
    evaluationType: StateChangeEvaluationType | None = None


class DecisionConditionalWorkflow(FewsModel):
    variableId: list[str] = Field(min_length=1)
    stateChanges: StateChanges
    workflowId: str


class DecisionEvaluation(FewsModel):
    initialConditionalWorkflow: DecisionInitialConditionalWorkflow
    conditionalWorkflow: DecisionConditionalWorkflow


class DecisionModule(FewsModel):
    barrierConfiguration: list[str] = Field(min_length=1)
    variable: list[DecisionVariableDefinition] = Field(min_length=1)
    rules: Rules
    decisionTree: list[DecisionTree] = Field(min_length=1)
    decisionEvaluation: DecisionEvaluation
