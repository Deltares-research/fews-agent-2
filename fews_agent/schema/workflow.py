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

    Reused as the shape for all scalar property kinds (string / int /
    float / double / bool): each is `key` + `value` (both kept as str to
    preserve placeholders and exact source text) + optional description.
    """

    key: str
    value: str
    description: str | None = None


class DateTimeProperty(FewsModel):
    """`<dateTime key="..." date="..." time="..."/>` — split date/time
    attributes rather than a single value (XSD DateTimePropertyComplexType)."""

    key: str
    date: str
    time: str
    description: str | None = None


class LocationAttributeProperty(FewsModel):
    """Property whose value is pulled from a location attribute."""

    key: str
    locationId: str
    attributeId: str


class LoopLocationProperty(FewsModel):
    """Property resolved per loop location via a relation + attribute."""

    key: str
    attributeId: str
    locationRelationId: str | None = None
    defaultValue: str | None = None


class QualifierAttributeProperty(FewsModel):
    key: str
    qualifierId: str
    attributeId: str


class ParameterAttributeProperty(FewsModel):
    key: str
    parameterId: str
    attributeId: str


class ModuleInstanceAttributeProperty(FewsModel):
    key: str
    moduleInstanceId: str
    attributeId: str


class ActivityModuleInstanceProperty(FewsModel):
    """Resolves an attribute of the activity's own module instance."""

    key: str
    attributeId: str


class WorkflowProperties(FewsModel):
    """`<properties>` wrapper. XSD: optional description, then any mix of
    typed scalar entries (string / int / float / double / bool / dateTime)
    and attribute-sourced entries (location / loopLocation / qualifier /
    parameter / moduleInstance / activityModuleInstance)."""

    description: str | None = None
    string: list[WorkflowProperty] = Field(default_factory=list)
    int: list[WorkflowProperty] = Field(default_factory=list)
    float: list[WorkflowProperty] = Field(default_factory=list)
    double: list[WorkflowProperty] = Field(default_factory=list)
    bool: list[WorkflowProperty] = Field(default_factory=list)
    dateTime: list[DateTimeProperty] = Field(default_factory=list)
    locationAttribute: list[LocationAttributeProperty] = Field(default_factory=list)
    loopLocationAttribute: list[LoopLocationProperty] = Field(default_factory=list)
    qualifierAttribute: list[QualifierAttributeProperty] = Field(default_factory=list)
    parameterAttribute: list[ParameterAttributeProperty] = Field(default_factory=list)
    moduleInstanceAttribute: list[ModuleInstanceAttributeProperty] = Field(
        default_factory=list
    )
    activityModuleInstanceAttribute: list[ActivityModuleInstanceProperty] = Field(
        default_factory=list
    )


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


class ModuleInstanceIdsChoice(FewsModel):
    """XSD ModuleInstanceIdsChoice — supply exactly one form: a list of
    explicit ``moduleInstanceId``s, a list of ``moduleInstanceIdPattern``s
    (``*``/``?`` wildcards), or a single ``moduleInstanceSetId``."""

    moduleInstanceId: list[str] = Field(default_factory=list)
    moduleInstanceIdPattern: list[str] = Field(default_factory=list)
    moduleInstanceSetId: str | None = None

    @model_validator(mode="after")
    def _exactly_one_form(self) -> ModuleInstanceIdsChoice:
        forms = [
            bool(self.moduleInstanceId),
            bool(self.moduleInstanceIdPattern),
            self.moduleInstanceSetId is not None,
        ]
        if sum(forms) != 1:
            raise ValueError(
                "supply exactly one of moduleInstanceId[] / "
                "moduleInstanceIdPattern[] / moduleInstanceSetId"
            )
        return self


class Completed(ModuleInstanceIdsChoice):
    """`<completed>` — mark module instances completed (read-only) for the
    rest of the running workflow."""


class DeleteTemporary(ModuleInstanceIdsChoice):
    """`<deleteTemporary>` — explicitly delete temporary series early
    rather than waiting for the end of the workflow/partition."""


class Parallel(FewsModel):
    """`<parallel>` — run sub-items concurrently. Sub-items are activities
    and/or sequences (XSD activityOrSequenceChoice). ``forecastingShellCount``
    distributes the loop across multiple forecasting shells.

    Note: like the root, sub-items are modelled as per-kind lists, so a
    parallel that *interleaves* activities and sequences round-trips
    grouped-by-kind rather than in source order (XSD-valid either way)."""

    properties: WorkflowProperties | None = None
    multipleForecastingShells: bool | None = None
    forecastingShellCount: int | str | None = None
    activity: list[WorkflowActivity] = Field(default_factory=list)
    sequence: list["Sequence"] = Field(default_factory=list)


class Sequence(FewsModel):
    """`<sequence>` — run sub-items one by one, optionally applying shared
    ``properties`` to all of them. Sub-items: activity / parallel /
    completed / deleteTemporary (modelled as per-kind lists; see Parallel)."""

    properties: WorkflowProperties | None = None
    activity: list[WorkflowActivity] = Field(default_factory=list)
    parallel: list[Parallel] = Field(default_factory=list)
    completed: list[Completed] = Field(default_factory=list)
    deleteTemporary: list[DeleteTemporary] = Field(default_factory=list)


Parallel.model_rebuild()
Sequence.model_rebuild()


class Workflow(FewsModel):
    """Root of a WorkflowFile.

    The XSD root is a single ``<choice maxOccurs="unbounded">`` over
    activity / parallel / sequence / completed / deleteTemporary. We model
    each kind as its own list: this covers the full element set and is
    XSD-valid (the choice accepts any ordering), but a workflow that
    *interleaves* different kinds round-trips grouped-by-kind rather than
    in exact source order. The overwhelmingly common case — a flat list of
    ``activity`` — is byte-faithful."""

    activity: list[WorkflowActivity] = Field(default_factory=list)
    parallel: list[Parallel] = Field(default_factory=list)
    sequence: list[Sequence] = Field(default_factory=list)
    completed: list[Completed] = Field(default_factory=list)
    deleteTemporary: list[DeleteTemporary] = Field(default_factory=list)
    properties: WorkflowProperties | None = None
    version: str = "1.1"

    @model_validator(mode="after")
    def _at_least_one_item(self) -> Workflow:
        if not (
            self.activity or self.parallel or self.sequence
            or self.completed or self.deleteTemporary
        ):
            raise ValueError(
                "workflow: supply at least one activity / parallel / "
                "sequence / completed / deleteTemporary"
            )
        return self
