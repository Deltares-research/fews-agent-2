"""Workflow.xml — ordered list of activities that FEWS runs as a unit.

An activity targets EITHER a module instance (runs that module config)
OR another workflow (nested workflow). `moduleConfigFileName` optionally
overrides which config file the instance uses — essential when a single
moduleInstanceId is served by several template variants.

Top-level `<properties>` carry `<string key=".." value=".."/>` entries
that drive `$PLACEHOLDER$` substitution inside the module templates at
FEWS runtime. Activities may also carry local `<properties>` overriding
specific keys for that activity only.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel
from .ids import LocationSetId, ModuleInstanceId, WorkflowId


class WorkflowProperty(FewsModel):
    """One key/value property — XML: `<string key="..." value="..."/>`.

    `value` can contain FEWS runtime placeholders (`$MODELNAME2$`,
    `ECCCStations$REGION$`, `@pattern@`) — passed through verbatim.
    """

    key: str
    value: str


class WorkflowProperties(FewsModel):
    """`<properties>` wrapper around zero-or-more `<string>` entries."""

    string: list[WorkflowProperty] = Field(default_factory=list)


class EnsembleMemberIndexRange(FewsModel):
    """Sub-range of ensemble members the activity applies to."""

    start: int
    end: int


class ActivityEnsemble(FewsModel):
    """`<ensemble>` block inside an activity.

    Two forms observed in the tutorial:
      - bounded: `<ensembleMemberIndexRange start end/>` — for REPS imports
      - looping: `<runInLoop>true</runInLoop>` — for REPS model runs
    """

    ensembleId: str
    ensembleMemberIndexRange: EnsembleMemberIndexRange | None = None
    runInLoop: bool | None = None


class WorkflowActivity(FewsModel):
    """One `<activity>` block.

    Invariant: exactly one of `moduleInstanceId` or `workflowId` is set.
    `runIndependent` is optional — some tutorial activities omit it
    (FEWS applies its own default).
    `loopLocationSetId` and `ensemble` are optional add-ons that drive
    per-location or per-ensemble-member looping of the activity.
    """

    runIndependent: bool | None = None
    moduleInstanceId: ModuleInstanceId | None = None
    workflowId: WorkflowId | None = None
    moduleConfigFileName: str | None = None
    loopLocationSetId: LocationSetId | None = None
    ensemble: ActivityEnsemble | None = None
    properties: WorkflowProperties | None = None

    @model_validator(mode="after")
    def _exactly_one_target(self) -> WorkflowActivity:
        has_mi = self.moduleInstanceId is not None
        has_wf = self.workflowId is not None
        if has_mi == has_wf:
            raise ValueError(
                "activity: supply exactly one of moduleInstanceId or workflowId"
            )
        return self


class Workflow(FewsModel):
    """Root of a WorkflowFile."""

    activity: list[WorkflowActivity] = Field(min_length=1)
    properties: WorkflowProperties | None = None
    version: str = "1.1"
