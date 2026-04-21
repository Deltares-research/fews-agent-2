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

from .common import FewsModel, UnitMultiplier
from .ids import TopologyNodeId, WorkflowId


class TopologyNodeLeaf(FewsModel):
    """`<node>` — terminal entry that runs or links to a workflow."""

    id: TopologyNodeId
    name: str | None = None
    workflowId: WorkflowId | None = None
    url: str | None = None
    graceTime: UnitMultiplier | None = None
    localRun: bool | None = None
    showRunApprovedForecastButton: bool | None = None


class TopologyNodeGroup(FewsModel):
    """`<nodes>` — container of child groups and/or leaves. Recursive."""

    id: TopologyNodeId
    name: str | None = None
    nodes: list[TopologyNodeGroup] = Field(default_factory=list)
    node: list[TopologyNodeLeaf] = Field(default_factory=list)


class Topology(FewsModel):
    """Root of Topology.xml."""

    nodes: list[TopologyNodeGroup] = Field(min_length=1)
    enableAutoRun: bool | None = None
    enableAutoSelectParameters: bool | None = None
    enableSelectNodesFromMap: bool | None = None
