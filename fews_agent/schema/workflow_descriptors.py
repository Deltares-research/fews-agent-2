"""WorkflowDescriptors.xml — declares workflowId with UI + scheduling metadata."""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel, TimeStep
from .ids import WorkflowId


class WorkflowDescriptor(FewsModel):
    # Elements in XSD sequence order
    description: str | None = None
    workflowFileName: str | None = None
    inputWorkflowId: list[str] = Field(default_factory=list)
    timeZone: str | None = None
    allowSelection: bool | None = None
    cardinalTimeStep: TimeStep | None = None
    minForecastLength: dict[str, Any] | None = None
    maxForecastLength: dict[str, Any] | None = None
    stateSelection: dict[str, Any] | None = None
    shiftAllExportedStatesToTime0: bool | None = None
    runExpiryTime: dict[str, Any] | None = None
    schedulingAllowed: bool | None = None
    maxSchedulingPeriod: dict[str, Any] | None = None
    defaultSchedulingPeriod: dict[str, Any] | None = None
    minSchedulingInterval: dict[str, Any] | None = None
    maxNumberRuns: int | None = None
    viewPermission: str | None = None
    runPermission: str | None = None
    approvePermission: str | None = None
    deletePermission: str | None = None
    deleteByCreatorAllowed: bool | None = None
    # XSD choice: properties (+editableProperty[]) or moduleConfigProperties
    properties: dict[str, Any] | None = None
    editableProperty: list[str] = Field(default_factory=list)
    moduleConfigProperties: dict[str, Any] | None = None
    enabledModifierGroups: dict[str, Any] | None = None
    maxEnsembleParts: int | None = None
    waterCoachDelay: dict[str, Any] | None = None
    timeOut: dict[str, Any] | None = None
    approvalEventCode: str | None = None
    whatIfTemplateId: str | None = None
    whatIfScenarioRequired: bool | None = None
    # Attributes
    id: WorkflowId
    stateWorkflowId: str | None = None
    name: str | None = None
    visible: bool | None = None
    forecast: bool | None = None
    waitWhenAlreadyRunning: bool | None = None
    allowApprove: bool | None = None
    allowEnsembleMemberSelection: bool | None = None
    autoApprove: bool | None = None
    autoSetSystemTime: bool | None = None
    showWarningInLogCompletion: bool | None = None
    onlyCheckThresholdsOfChangedSeries: bool | None = None


class WorkflowDescriptorNode(FewsModel):
    """Tree-node entry. XSD TreeNodeComplexType requires ``name`` attr
    plus the NodeElements group (description + choice of workflowId /
    nested node / nodeId ref). Simplified here to name + workflowId[]
    since that's the common ManualForecast-dialog flat form."""

    name: str
    workflowId: list[WorkflowId] = Field(default_factory=list)


class WorkflowDescriptorGroupNode(FewsModel):
    """Root-level named-node entry (XSD GroupNodeComplexType) — same
    body as TreeNode but with an ``id`` attr. Referenced by nodeId from
    rootNode.node children to share sub-trees across descriptor files."""

    id: str
    name: str | None = None
    workflowId: list[WorkflowId] = Field(default_factory=list)


class WorkflowDescriptorRootNode(FewsModel):
    node: list[WorkflowDescriptorNode] = Field(default_factory=list)


class WorkflowDescriptors(FewsModel):
    workflowDescriptor: list[WorkflowDescriptor] = Field(min_length=1)
    rootNode: WorkflowDescriptorRootNode | None = None
    node: list[WorkflowDescriptorGroupNode] = Field(default_factory=list)
    version: str = "1.0"
