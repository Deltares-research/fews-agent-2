"""Topology.xml — UI navigation tree over workflows.

Two element shapes:
  - `<nodes>` (plural) is a group that contains child `<nodes>` and/or
    `<node>` leaves.
  - `<node>` (singular) is a leaf that points at a workflow.

Both carry an `id` attribute (TopologyNodeId). Leaves reference a
workflowId declared by a WorkflowFile (by filename).
"""
from __future__ import annotations

from pydantic import Field

from pydantic import Field

from .common import FewsModel, UnitMultiplier
from .ids import ModifierId, TopologyNodeId, WorkflowId


class TopologyNodeLeaf(FewsModel):
    """`<node>` — terminal entry that runs or links to a workflow.

    `visibleModifierGroup` lists modifiersGroup ids (see ModifierTypes)
    that the UI should surface when this node is active — tutorial uses
    this on forecast-run nodes to reveal NWP-specific modifiers.
    """

    # Attrs
    id: TopologyNodeId
    name: str | None = None
    # XSD sequence: previousNodeId[], nextNodeId, locationId/locationSetId choice,
    # tabularLocationId[], runOptionsGroup (workflowId/url/graceTime/visibleModifierGroup),
    # componentSettingsId, LocalRunOptionsChoice (localRun), showRunApprovedForecastButton,
    # then the color fields.
    previousNodeId: list[str] = Field(default_factory=list)
    nextNodeId: str | None = None
    locationId: list[str] = Field(default_factory=list)
    locationSetId: str | None = None
    tabularLocationId: list[str] = Field(default_factory=list)
    workflowId: WorkflowId | None = None
    url: str | None = None
    graceTime: UnitMultiplier | None = None
    visibleModifierGroup: list[ModifierId] = Field(default_factory=list)
    componentSettingsId: str | None = None
    localRun: bool | None = None
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


class Topology(FewsModel):
    """Root of Topology.xml.

    Final element is an XSD choice of ``groupId`` / ``nodes`` repeating
    unbounded. ``groupId`` references a topology sub-group configured in
    a separate topologyGroup.xml file, allowing the topology to be
    split across files.
    """

    nodes: list[TopologyNodeGroup] = Field(default_factory=list)
    groupId: list[str] = Field(default_factory=list)
    forecasterHelperDirectories: str | None = None
    enableOriginalButtons: bool | None = None
    hideThresholdsButton: bool | None = None
    hideNextSegmentButton: bool | None = None
    hidePreviousSegmentButton: bool | None = None
    enableAutoRun: bool | None = None
    enableRunUpstreamServerNodes: bool | None = None
    enableRunAllPreviousNodes: bool | None = None
    enableSelectNodesFromMap: bool | None = None
    enableAutoClearParameters: bool | None = None
    enableAutoSelectParameters: bool | None = None
    enableAutoSaveOnRun: bool | None = None
    enableCrossGroupNodeReferencing: bool | None = None
    enableSelectLastNodeOnStartUp: bool | None = None
    selectFirstPlotOnSelectionChange: bool | None = None
