"""TaskPropertiesPredefined.xml — predefined batch tasks.

XSD root is a ``choice maxOccurs=unbounded`` over ``batchTask`` and
``taskProperties`` — same parallel-list pattern as other bags.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel, Period, TimeStep, UnitMultiplier
from .task_properties import TaskProperties


class OverrulingModuleInstanceRunKey(FewsModel):
    """``<overrulingActiveModuleInstanceRuns workflowId="..."><moduleInstanceId/>+``"""

    workflowId: str
    moduleInstanceId: list[str] = Field(min_length=1)


class BatchTask(FewsModel):
    """XSD choice: interval (UnitMultiplier) XOR intervalTimeStep (TimeStep)."""

    period: Period
    taskProperties: list[TaskProperties] = Field(min_length=1)
    interval: UnitMultiplier | None = None
    intervalTimeStep: TimeStep | None = None
    overrulingActiveModuleInstanceRuns: list[OverrulingModuleInstanceRunKey] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def _one_interval(self) -> BatchTask:
        if (self.interval is None) == (self.intervalTimeStep is None):
            raise ValueError(
                "batchTask: supply exactly one of interval or intervalTimeStep"
            )
        return self


class TaskPropertiesPredefined(FewsModel):
    """XSD choice-unbounded over batchTask / taskProperties — parallel lists."""

    batchTask: list[BatchTask] = Field(default_factory=list)
    taskProperties: list[TaskProperties] = Field(default_factory=list)

    @model_validator(mode="after")
    def _at_least_one(self) -> TaskPropertiesPredefined:
        if not self.batchTask and not self.taskProperties:
            raise ValueError(
                "taskPropertiesPredefined: supply at least one batchTask or "
                "taskProperties entry"
            )
        return self
