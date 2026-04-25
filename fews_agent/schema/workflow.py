"""Workflow.xml — ordered list of activities that FEWS runs as a unit.

An activity targets EITHER a module instance (runs that module config)
OR another workflow (nested) OR a predefined activity name.
`moduleConfigFileName` optionally overrides which config file the
instance uses.

Top-level `<properties>` carry `<string key=".." value=".."/>` entries
that drive `$PLACEHOLDER$` substitution inside the module templates at
FEWS runtime. Activities may also carry local `<properties>` overriding
specific keys for that activity only.

XSD notes:
  - The root allows a choice of activity / parallel / sequence /
    completed / deleteTemporary — only ``activity`` is modelled here
    (tutorial exercises no other; adding the rest is future work).
  - Activity has three XSD variants: moduleInstance form
    (defaultFlagSource + flagSourceColumnId + moduleInstanceId +
    moduleConfigFileName), workflow form (workflowId), and predefined
    form (predefinedActivity + optional moduleInstanceId).
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel
from .ids import LocationId, LocationSetId, ModuleInstanceId, WorkflowId


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

    XSD choice over four member selectors (all optional):
    ``ensembleMemberId`` / ``ensembleMemberIndex`` /
    ``ensembleMemberIndexRange`` / ``ensembleMemberIdRegularExpression``.
    ``runInLoop`` is required (XSD default=true but the element itself
    is required).
    """

    ensembleId: str
    runInLoop: bool = True
    ensembleMemberId: str | None = None
    ensembleMemberIndex: int | None = None
    ensembleMemberIndexRange: EnsembleMemberIndexRange | None = None
    ensembleMemberIdRegularExpression: str | None = None

    @model_validator(mode="after")
    def _one_member_selector(self) -> ActivityEnsemble:
        variants = [
            self.ensembleMemberId is not None,
            self.ensembleMemberIndex is not None,
            self.ensembleMemberIndexRange is not None,
            self.ensembleMemberIdRegularExpression is not None,
        ]
        if sum(variants) > 1:
            raise ValueError(
                "ensemble: at most one of ensembleMemberId / "
                "ensembleMemberIndex / ensembleMemberIndexRange / "
                "ensembleMemberIdRegularExpression"
            )
        return self


class ActivityEnabled(FewsModel):
    """Attribute-only — ``<enabled locationId="..." attributeId="..."/>``.
    If present and the referenced location attribute is false, the
    activity is excluded from the run."""

    locationId: LocationId
    attributeId: str


class WorkflowActivity(FewsModel):
    """One `<activity>` block.

    XSD choice between three target variants (exactly one must be set):
      - moduleInstanceId (+ optional moduleConfigFileName, defaultFlagSource,
        flagSourceColumnId)
      - workflowId
      - predefinedActivity (+ optional moduleInstanceId)

    ``fallbackActivity`` is recursive — runs when the primary activity
    fails (independent of runIndependent). ``enable`` and ``enabled``
    are an XSD choice (at most one); ``enable`` is a simple boolean /
    placeholder, ``enabled`` references a location attribute.
    """

    # Target — XSD choice (moduleInstanceId vs workflowId vs predefinedActivity)
    moduleInstanceId: ModuleInstanceId | None = None
    workflowId: WorkflowId | None = None
    predefinedActivity: str | None = None
    moduleConfigFileName: str | None = None
    defaultFlagSource: str | None = None
    flagSourceColumnId: str | None = None
    # Common optional children
    properties: WorkflowProperties | None = None
    enable: str | None = None
    enabled: ActivityEnabled | None = None
    runIndependent: bool | None = None
    downloadMissingDataFromArchive: bool | None = None
    downloadMissingDataFromArchiveForManualTasksOnly: bool | None = None
    downloadMissingStatesFromArchive: bool | None = None
    fallbackActivity: "WorkflowActivity | None" = None
    ensemble: ActivityEnsemble | None = None
    loopLocationSetId: LocationSetId | None = None
    skipNonExistingLoopLocationSet: bool | None = None
    description: str | None = None
    # Attributes
    logStartedAsDebug: bool | None = None
    logFinishedAsDebug: bool | None = None

    @model_validator(mode="after")
    def _exactly_one_target(self) -> WorkflowActivity:
        has_mi = self.moduleInstanceId is not None
        has_wf = self.workflowId is not None
        has_pre = self.predefinedActivity is not None
        # predefinedActivity + moduleInstanceId is a valid combo (XSD variant 3)
        if has_pre:
            if has_wf:
                raise ValueError(
                    "activity: predefinedActivity is mutually exclusive with workflowId"
                )
        else:
            if has_mi == has_wf:
                raise ValueError(
                    "activity: supply exactly one of moduleInstanceId, "
                    "workflowId, or predefinedActivity"
                )
        if self.enable is not None and self.enabled is not None:
            raise ValueError(
                "activity: at most one of enable / enabled (XSD choice)"
            )
        if self.downloadMissingDataFromArchiveForManualTasksOnly is not None \
                and self.downloadMissingDataFromArchive is None:
            raise ValueError(
                "activity: downloadMissingDataFromArchiveForManualTasksOnly "
                "requires downloadMissingDataFromArchive (XSD inner sequence)"
            )
        return self


WorkflowActivity.model_rebuild()


class Workflow(FewsModel):
    """Root of a WorkflowFile.

    Only the ``activity`` variant of the root XSD choice is modelled;
    parallel / sequence / completed / deleteTemporary are not in scope.
    """

    activity: list[WorkflowActivity] = Field(min_length=1)
    properties: WorkflowProperties | None = None
    version: str = "1.1"
