"""WorkflowDescriptors.xml — declares workflowId with UI + scheduling metadata."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel
from .ids import WorkflowId


class CardinalTimeStepRef(FewsModel):
    """Either `<cardinalTimeStep id="..."/>` (named ref) or
    `<cardinalTimeStep unit=".." multiplier=".." timeZone=".."/>` (inline)."""

    id: str | None = None
    unit: str | None = None
    multiplier: int | str | None = None
    timeZone: str | None = None


class WorkflowDescriptor(FewsModel):
    id: WorkflowId
    name: str | None = None
    visible: bool | None = None
    forecast: bool | None = None
    autoApprove: bool | None = None
    allowApprove: bool | None = None
    description: str | None = None
    cardinalTimeStep: CardinalTimeStepRef | None = None


class WorkflowDescriptorNode(FewsModel):
    """Grouping node inside `<rootNode>` — bundles workflow ids under a
    display name for the UI tree."""

    name: str
    workflowId: list[WorkflowId] = Field(default_factory=list)


class WorkflowDescriptorRootNode(FewsModel):
    node: list[WorkflowDescriptorNode] = Field(default_factory=list)


class WorkflowDescriptors(FewsModel):
    workflowDescriptor: list[WorkflowDescriptor] = Field(min_length=1)
    rootNode: WorkflowDescriptorRootNode | None = None
    version: str = "1.0"
