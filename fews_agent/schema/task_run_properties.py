"""TaskRunProperties.xml — runtime task-run record.

FEWS emits this file to describe a specific task run: the template
TaskProperties, the run id, T0, and various optional per-run
fields (forecast times, used module instance runs, expiry, etc.).

Two deprecated XSD slots (``archiveTaskRun`` — old archive,
``usedConfFiles`` — obsolete) are accepted as ``dict[str, Any]``
passthroughs rendered via ``dict_to_xml`` for XSD-complete round-trip.

``ModuleInstanceRunKey`` and ``ModifierDescriptorKey`` are reused
from archive_metadata (identical XSD complexTypes).
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel, RelativePeriod
from .archive_metadata import ModifierDescriptorKey, ModuleInstanceRunKey
from .task_properties import TaskProperties


class ExternalForecastTime(FewsModel):
    id: str
    date: str
    time: str


class InputProduct(FewsModel):
    """Recursive attribute-only type — an inputProduct may itself
    contain child inputProducts listing the products it was built from."""

    productId: str
    forecastDate: str
    forecastTime: str
    productDate: str
    productTime: str
    inputProduct: "list[InputProduct]" = Field(default_factory=list)


InputProduct.model_rebuild()


class UnexpectedColdStateUsed(FewsModel):
    moduleInstanceId: str
    stateSearchRelativePeriod: RelativePeriod


class TaskRunProperties(FewsModel):
    taskProperties: TaskProperties
    taskRunId: str
    time0: str  # xsd:dateTime — pass-through ISO string
    externalForecastTime: list[ExternalForecastTime] = Field(default_factory=list)
    inputProduct: list[InputProduct] = Field(default_factory=list)
    # archiveTaskRun: deprecated (old archive) — dict passthrough
    archiveTaskRun: dict[str, Any] | None = None
    # usedConfFiles: obsolete — dict passthrough
    usedConfFiles: dict[str, Any] | None = None
    usedModuleInstanceRuns: list[ModuleInstanceRunKey] = Field(default_factory=list)
    usedModifiers: list[ModifierDescriptorKey] = Field(default_factory=list)
    expiryTime: str | None = None
    earliestExportedStateTime: str | None = None
    latestExportedStateTime: str | None = None
    unexpectedColdStateUsed: list[UnexpectedColdStateUsed] = Field(default_factory=list)
    backupWarmStateUsed: bool | None = None
