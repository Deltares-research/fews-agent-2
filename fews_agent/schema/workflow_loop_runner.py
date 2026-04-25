"""WorkflowLoopRunner.xml — re-run a workflow over periods found by a trigger series."""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from .common import FewsModel, RelativeViewPeriod, TimeSeriesSet, TimeStep


class RunPeriodOptions(FewsModel):
    alwaysFullPeriod: bool | None = None


class ValueTrigger(FewsModel):
    timeSeriesSet: TimeSeriesSet
    valueOption: Literal["above", "below"]
    value: Decimal
    relativeRunWindow: RelativeViewPeriod


class StepValueTrigger(FewsModel):
    timeSeriesSet: TimeSeriesSet
    stepValueOption: Literal["maximum", "minimum"]
    stepSize: TimeStep
    relativeRunWindow: RelativeViewPeriod


class TriggerOptions(FewsModel):
    """XSD choice between valueTrigger and stepValueTrigger — exactly one."""

    valueTrigger: ValueTrigger | None = None
    stepValueTrigger: StepValueTrigger | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> TriggerOptions:
        if (self.valueTrigger is None) == (self.stepValueTrigger is None):
            raise ValueError(
                "triggerOptions: supply exactly one of valueTrigger or stepValueTrigger"
            )
        return self


class WorkflowLoopRunner(FewsModel):
    """Root of WorkflowLoopRunner.xml."""

    workflowId: str
    runPeriodOptions: RunPeriodOptions | None = None
    triggerOptions: list[TriggerOptions] = Field(min_length=1)
