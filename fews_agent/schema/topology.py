"""Topology.xml — UI navigation tree over workflows.

Two element shapes:
  - `<nodes>` (plural) is a group that contains child `<nodes>` and/or
    `<node>` leaves.
  - `<node>` (singular) is a leaf that points at a workflow.

Both carry an `id` attribute (TopologyNodeId). Leaves reference a
workflowId declared by a WorkflowFile (by filename).

The `<node>` leaf carries a very large optional surface (run options,
state/forecast-time selection, display references, modifier-display
controls, a location-constraint filter, a properties bag, WebOC display
ids). It is modelled here as a flat optional superset rendered in XSD
sequence order; the deriver-produced common case (id + name + workflowId)
renders unchanged. Where the XSD uses a `<choice>`, the model is a
permissive superset and XSD validation is the loud gate.
"""
from __future__ import annotations

from pydantic import Field

from .common import (
    CalendarTimeSpan,
    FewsModel,
    RelativePeriod,
    RelativeTime,
    RelativeViewPeriod,
    TimeShift,
    TimeStep,
    TimeZone,
    UnitMultiplier,
)
from .ids import ModifierId, TopologyNodeId, WorkflowId


# --- shared sub-structures --------------------------------------------

class TopoStringProperty(FewsModel):
    key: str
    value: str


class TopoBoolProperty(FewsModel):
    key: str
    value: bool


class TopoDateTimeProperty(FewsModel):
    key: str
    date: str
    time: str


class TopologyProperties(FewsModel):
    """`<properties>` bag (PropertiesComplexType) — typed key/value entries
    referenced as `$key$` in workflows/module configs."""

    description: str | None = None
    string: list[TopoStringProperty] = Field(default_factory=list)
    int: list[TopoStringProperty] = Field(default_factory=list)
    float: list[TopoStringProperty] = Field(default_factory=list)
    double: list[TopoStringProperty] = Field(default_factory=list)
    bool: list[TopoBoolProperty] = Field(default_factory=list)
    dateTime: list[TopoDateTimeProperty] = Field(default_factory=list)


class UnmodifiedDateTimeAttributeValue(FewsModel):
    attributeId: str
    offset: UnitMultiplier
    timeStep: TimeStep


class CustomInfoLabel(FewsModel):
    labelText: str
    locationId: str
    overrulingUnmodifiedDateTimeAttributeValue: list[
        UnmodifiedDateTimeAttributeValue
    ] = Field(default_factory=list)


class GridDisplaySelection(FewsModel):
    groupId: str
    plotId: str | None = None


class FixedColdState(FewsModel):
    coldState: UnitMultiplier | None = None
    locationId: str
    modifierTypeId: str
    fixedColdStateLocationAttributeId: str
    fixedColdStateGroupLocationAttributeId: str


class ColdStateFromCurrentRun(FewsModel):
    workflowId: str
    coldState: UnitMultiplier | None = None


# --- location-constraint filter (recursive) ---------------------------

class IdConstraint(FewsModel):
    """`<idStartsWith>` / `<idEndsWith>` / `<idContains>` — text body plus
    one of prefix/postfix/contains."""

    prefix: str | None = None
    postfix: str | None = None
    contains: str | None = None


class AttributeConstraint(FewsModel):
    """Attribute-value constraints — `id` (attribute id) plus an optional
    matcher (prefix/postfix/contains/equals) and modifierDependent flag."""

    id: str
    prefix: str | None = None
    postfix: str | None = None
    contains: str | None = None
    equals: str | None = None
    modifierDependent: bool | None = None


class RelatedLocationExists(FewsModel):
    locationRelationId: str


class Constraints(FewsModel):
    """XSD ConstraintsComplexType — a location filter: an unbounded choice
    of id/attribute matchers and the boolean combinators not/anyValid/
    allValid (recursive)."""

    idStartsWith: list[IdConstraint] = Field(default_factory=list)
    idEndsWith: list[IdConstraint] = Field(default_factory=list)
    idContains: list[IdConstraint] = Field(default_factory=list)
    relatedLocationExists: list[RelatedLocationExists] = Field(default_factory=list)
    attributeExists: list[AttributeConstraint] = Field(default_factory=list)
    attributeTextStartsWith: list[AttributeConstraint] = Field(default_factory=list)
    attributeTextEndsWith: list[AttributeConstraint] = Field(default_factory=list)
    attributeTextContains: list[AttributeConstraint] = Field(default_factory=list)
    attributeTextEquals: list[AttributeConstraint] = Field(default_factory=list)
    attributeTrue: list[AttributeConstraint] = Field(default_factory=list)
    attributeFalse: list[AttributeConstraint] = Field(default_factory=list)
    not_: "Constraints | None" = Field(default=None, alias="not")
    anyValid: "Constraints | None" = None
    allValid: "Constraints | None" = None


Constraints.model_rebuild()


# --- node leaf ---------------------------------------------------------

class TopologyNodeLeaf(FewsModel):
    """`<node>` — terminal entry that runs or links to a workflow.

    Fields follow XSD sequence order across the runOptions / connectivity /
    sharedNodeOptions groups. All but `id` are optional.
    """

    # Attrs
    id: TopologyNodeId
    name: str | None = None
    # connectivity (head)
    previousNodeId: list[str] = Field(default_factory=list)
    nextNodeId: str | None = None
    locationId: list[str] = Field(default_factory=list)
    locationSetId: str | None = None
    tabularLocationId: list[str] = Field(default_factory=list)
    # runOptionsGroup
    properties: TopologyProperties | None = None
    workflowId: WorkflowId | None = None
    refreshConfigAfterCompletion: bool | None = None
    secondaryWorkflowId: list[str] = Field(default_factory=list)
    runSecondaryWorkflowAtServer: bool | None = None
    runSecondaryWorkflowWithTaskRunPropertiesFromIFD: bool | None = None
    enableSecondaryWorkflow: str | None = None
    moduleInstanceId: list[str] = Field(default_factory=list)
    enableAutoApprove: bool | None = None
    # forecast-time choice: fixed dates ...
    startDateTime: str | None = None
    enableEarlierStartTime: bool | None = None
    enableLaterStartTime: bool | None = None
    endDateTime: str | None = None
    enableEarlierEndTime: bool | None = None
    enableLaterEndTime: bool | None = None
    # ... or flexible dates: state selection
    coldState: UnitMultiplier | None = None
    coldStateFromCurrentRun: ColdStateFromCurrentRun | None = None
    coldStateStartTime: str | None = None
    warmStateSelectionPeriod: RelativePeriod | None = None
    warmState: UnitMultiplier | None = None
    noInitialState: bool | None = None
    fixedColdState: FixedColdState | None = None
    forecastLength: UnitMultiplier | None = None
    cardinalTimeStepForecastLength: TimeStep | None = None
    initialForecastLengthCardinalTimeStep: TimeStep | None = None
    useForecastLengthFromInteractiveForecastDisplay: bool | None = None
    relativePeriod: RelativePeriod | None = None
    relativeStartTime: RelativeTime | None = None
    cardinalTimeStepStartTime: TimeStep | None = None
    initialStartTimeCardinalTimeStep: TimeStep | None = None
    cardinalTimeStepEndTime: TimeStep | None = None
    initialEndTimeCardinalTimeStep: TimeStep | None = None
    timeZero: str | None = None
    timeZeroShift: TimeShift | None = None
    # connectivityOptionsGroup
    alwaysVisibleInForecasterNotes: bool | None = None
    mapExtentId: str | None = None
    filterId: list[str] = Field(default_factory=list)
    disableMap: bool | None = None
    displayGroupId: list[str] = Field(default_factory=list)
    displayId: str | None = None
    plotId: str | None = None
    dataDownloadDisplayId: str | None = None
    logDisplayId: str | None = None
    dynamicReportDisplayId: str | None = None
    webOCDashboardId: list[str] = Field(default_factory=list)
    webOCMicroFrontEndId: list[str] = Field(default_factory=list)
    documentDisplayId: str | None = None
    timeSeriesButtonsPanelId: str | None = None
    reportModuleInstanceId: str | None = None
    dataAnalysisDisplayId: str | None = None
    documentFile: str | None = None
    # sharedNodeOptionsGroup
    customInfoLabel: CustomInfoLabel | None = None
    showWorkflowDescriptionBox: bool | None = None
    disableAdvancedButton: bool | None = None
    hideModifiersOverviewPanel: bool | None = None
    areaId: str | None = None
    modifiersReadOnly: bool | None = None
    viewPermission: str | None = None
    runWorkflowLocallyPermission: str | None = None
    runWorkflowAtServerPermission: str | None = None
    runSecondaryWorkflowPermission: str | None = None
    defaultModifierId: ModifierId | None = None
    onlyAllowEditDefaultModifier: bool | None = None
    visibleModifierGroup: list[ModifierId] = Field(default_factory=list)
    attributeModifierLocationConstraint: Constraints | None = None
    graceTime: UnitMultiplier | None = None
    checkStatusPreviousServerRun: bool | None = None
    showMacroButton: bool | None = None
    gridDisplaySelection: GridDisplaySelection | None = None
    mainPanel: str | None = None
    displayConfigFileName: str | None = None
    tabId: str | None = None
    panelId: str | None = None
    explorerTaskName: str | None = None
    toolWindow: list[str] = Field(default_factory=list)
    url: str | None = None
    embedUrl: str | None = None
    useStatusParentNode: bool | None = None
    thresholdValueSetId: list[str] = Field(default_factory=list)
    scadaDisplayId: str | None = None
    scadaPanelId: str | None = None
    popupMessageServerRun: str | None = None
    popupMessageUncommittedModifiers: str | None = None
    thresholdIconRelativeViewPeriod: RelativePeriod | None = None
    icon: str | None = None
    iconId: str | None = None
    # tail
    componentSettingsId: str | None = None
    localRun: bool | None = None
    saveLocalRunEnabled: bool | None = None
    privateRunAtServer: bool | None = None
    publishPrivateRunEnabled: bool | None = None
    showRunApprovedForecastButton: bool | None = None
    backgroundSelectionColor: str | None = None
    backgroundNonSelectionColor: str | None = None
    textSelectionColor: str | None = None
    textNonSelectionColor: str | None = None


class TopologyNodeGroup(FewsModel):
    """`<nodes>` — container of child groups and/or leaves. Recursive."""

    id: TopologyNodeId
    name: str | None = None
    showModifiers: bool | None = None
    showRunApprovedForecastButton: bool | None = None
    nodes: list[TopologyNodeGroup] = Field(default_factory=list)
    node: list[TopologyNodeLeaf] = Field(default_factory=list)
    groupId: list[str] = Field(default_factory=list)
    backgroundSelectionColor: str | None = None
    backgroundNonSelectionColor: str | None = None
    textSelectionColor: str | None = None
    textNonSelectionColor: str | None = None


class MultipleNodesDirectory(FewsModel):
    """`<multipleNodesDirectory nodeIdPrefix="...">dir</multipleNodesDirectory>` —
    directory text body plus a nodeIdPrefix attribute."""

    nodeIdPrefix: str
    value: str | None = None


class ForecasterHelperDirectories(FewsModel):
    """`<forecasterHelperDirectories>` — directories the forecaster helper
    scans, by-node and per-prefix."""

    directory: list[str] = Field(default_factory=list)
    allNodesDirectory: list[str] = Field(default_factory=list)
    multipleNodesDirectory: list[MultipleNodesDirectory] = Field(default_factory=list)


class Topology(FewsModel):
    """Root of Topology.xml.

    Final element is an XSD choice of ``groupId`` / ``nodes`` repeating
    unbounded. ``groupId`` references a topology sub-group configured in
    a separate topologyGroup.xml file, allowing the topology to be
    split across files.
    """

    forecasterHelperDirectories: ForecasterHelperDirectories | None = None
    enableOriginalButtons: bool | None = None
    modifiersIconVisible: bool | None = None
    hideModifiersButton: bool | None = None
    hideThresholdsButton: bool | None = None
    hideNextSegmentButton: bool | None = None
    hidePreviousSegmentButton: bool | None = None
    enableAutoRun: bool | None = None
    enableAutoSelectParameters: bool | None = None
    enableAutoClearParameters: bool | None = None
    enableRunUpstreamServerNodes: bool | None = None
    enableRunAllPreviousNodes: bool | None = None
    enableSelectNodesFromMap: bool | None = None
    enableAutoSaveOnRun: bool | None = None
    enableCrossGroupNodeReferencing: bool | None = None
    enableSelectLastNodeOnStartUp: bool | None = None
    selectFirstPlotOnSelectionChange: bool | None = None
    nodes: list[TopologyNodeGroup] = Field(default_factory=list)
    groupId: list[str] = Field(default_factory=list)
