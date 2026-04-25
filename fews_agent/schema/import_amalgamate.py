"""ImportAmalgamate.xml — merges short-span import runs into compact
per-parameter time series to keep the datastore lean.

XSD structure: an optional inner sequence (workflow ids + minimalAge +
optional expiry), followed by three independent boolean flags. If any
workflow id is present, importRunMinimalAge is required by the XSD.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel, TimeStep


class ImportAmalgamate(FewsModel):
    """Root of ImportAmalgamate.xml."""

    workflowId: list[str] = Field(default_factory=list)
    workflowIdPattern: list[str] = Field(default_factory=list)
    importRunMinimalAge: TimeStep | None = None
    afterAmalgamateImportRunMetaDataExpiryTime: TimeStep | None = None
    amalgamateClosedServiceSessions: bool | None = None
    amalgamateOrphans: bool | None = None
    removeIdsNoLongerInConfig: bool | None = None

    @model_validator(mode="after")
    def _minimal_age_with_workflows(self) -> ImportAmalgamate:
        has_workflows = bool(self.workflowId) or bool(self.workflowIdPattern)
        if has_workflows and self.importRunMinimalAge is None:
            raise ValueError(
                "importAmalgamate: importRunMinimalAge is required when "
                "workflowId/workflowIdPattern are set"
            )
        return self
