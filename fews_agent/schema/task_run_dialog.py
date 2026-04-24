"""TaskRunDialog.xml — Task Run dialog configuration.

Groups one or more tasks per workflow. Each task is either:
  - a ``simpleTask`` (relativePeriod only), or
  - an ``operatorTask`` (panels with scenario/value/time editors).

The deprecated ``archiveTask`` (gone since 2017.02) and Neva-barrier
task variants are not modelled here; add them when a live config needs
them.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import DataVariable, FewsModel, RelativeViewPeriod, TimeSeriesSet


class PixelPosition(FewsModel):
    x: int | None = None
    y: int | None = None


class PixelDimension(FewsModel):
    width: int | None = None
    height: int | None = None


class TaskRunDialogTaskDependency(FewsModel):
    taskName: str
    vertex: list[PixelPosition] = Field(default_factory=list)


class TaskRunDialogFlowchart(FewsModel):
    taskSize: PixelDimension
    scale: int = 1


class TaskRunDialogScenarioEntry(FewsModel):
    id: str


class TaskRunDialogScenarioSelector(FewsModel):
    name: str
    selectedScenario: TaskRunDialogScenarioEntry | None = None
    scenario: list[TaskRunDialogScenarioEntry] = Field(min_length=1)
    enabled: bool | None = None


class TaskRunDialogValueEditor(FewsModel):
    """Choice: defaultFloatValue XOR defaultTimeSeriesSet."""

    name: str
    outputVariable: DataVariable
    unit: str | None = None
    defaultFloatValue: float | None = None
    defaultTimeSeriesSet: TimeSeriesSet | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def _one_default(self) -> TaskRunDialogValueEditor:
        if (self.defaultFloatValue is None) == (self.defaultTimeSeriesSet is None):
            raise ValueError(
                "valueEdit: supply exactly one of defaultFloatValue or defaultTimeSeriesSet"
            )
        return self


class TaskRunDialogValueNonEditable(FewsModel):
    """Choice: defaultFloatValue XOR defaultTimeSeriesSet."""

    name: str
    unit: str | None = None
    defaultFloatValue: float | None = None
    defaultTimeSeriesSet: TimeSeriesSet | None = None

    @model_validator(mode="after")
    def _one_default(self) -> TaskRunDialogValueNonEditable:
        if (self.defaultFloatValue is None) == (self.defaultTimeSeriesSet is None):
            raise ValueError(
                "valueNonEditable: supply exactly one of defaultFloatValue or "
                "defaultTimeSeriesSet"
            )
        return self


class TaskRunDialogTimeEditor(FewsModel):
    """Choice: defaultTimeValue XOR defaultTimeSeriesSet."""

    name: str
    outputVariable: DataVariable
    unit: str | None = None
    defaultTimeValue: str | None = None  # dateTime
    defaultTimeSeriesSet: TimeSeriesSet | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def _one_default(self) -> TaskRunDialogTimeEditor:
        if (self.defaultTimeValue is None) == (self.defaultTimeSeriesSet is None):
            raise ValueError(
                "timeEdit: supply exactly one of defaultTimeValue or defaultTimeSeriesSet"
            )
        return self


class TaskRunDialogPanel(FewsModel):
    """XSD inner-choice group maxOccurs=unbounded — modelled as parallel
    lists per editor kind; emitted in fixed order. Any order is valid."""

    name: str | None = None
    row: int | None = None
    column: int | None = None
    scenarioSelect: list[TaskRunDialogScenarioSelector] = Field(default_factory=list)
    valueEdit: list[TaskRunDialogValueEditor] = Field(default_factory=list)
    timeEdit: list[TaskRunDialogTimeEditor] = Field(default_factory=list)
    valueNonEditable: list[TaskRunDialogValueNonEditable] = Field(default_factory=list)


class TaskRunDialogTaskBase(FewsModel):
    name: str
    workflowId: str
    iconName: str | None = None
    disableRun: bool | None = None
    disableSchedule: bool | None = None
    explorerLocationId: str | None = None
    runLocally: bool | None = None
    center: PixelPosition | None = None
    dependency: list[TaskRunDialogTaskDependency] = Field(default_factory=list)


class TaskRunDialogSimpleTask(TaskRunDialogTaskBase):
    relativePeriod: RelativeViewPeriod


class TaskRunDialogOperatorTask(TaskRunDialogTaskBase):
    panel: list[TaskRunDialogPanel] = Field(default_factory=list)


class TaskRunDialogTaskGroup(FewsModel):
    """XSD choice-unbounded over simpleTask / operatorTask — parallel
    lists pattern."""

    name: str | None = None
    workflowId: str | None = None
    flowchart: TaskRunDialogFlowchart | None = None
    simpleTask: list[TaskRunDialogSimpleTask] = Field(default_factory=list)
    operatorTask: list[TaskRunDialogOperatorTask] = Field(default_factory=list)

    @model_validator(mode="after")
    def _at_least_one_task(self) -> TaskRunDialogTaskGroup:
        if not self.simpleTask and not self.operatorTask:
            raise ValueError(
                "taskGroup: supply at least one simpleTask or operatorTask"
            )
        return self


class TaskRunDialog(FewsModel):
    """Root of TaskRunDialog.xml."""

    taskGroup: list[TaskRunDialogTaskGroup] = Field(min_length=1)
    title: str | None = None
    showProperties: bool | None = None
