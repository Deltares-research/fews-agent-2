"""TopologyGroup.xml — extracted topology sub-tree, referenced by groupId
from a Topology.xml or another TopologyGroup.xml.

XSD root: ``topologyGroup`` (TopologyGroupComplexType).

Each ``group`` carries an ``id`` attribute and one or more ``nodes``
children. NodesComplexType is the full Topology nodes grammar (deeply
nested with run-options groups, state-selection choices, forecast
length groups, ...). Per CLAUDE.md "``dict[str, Any]`` for subtrees
deeper than 3 nesting levels" we keep the nodes payload as a
pass-through dict — only the root structure (group id) is typed.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel


class TopologyGroupEntry(FewsModel):
    """One ``<group id="...">`` entry — required id + 1..n nodes children."""

    id: str
    nodes: list[dict[str, Any]] = Field(min_length=1)


class TopologyGroup(FewsModel):
    """Root of TopologyGroup.xml."""

    group: list[TopologyGroupEntry] = Field(default_factory=list)
