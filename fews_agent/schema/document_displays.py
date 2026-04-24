"""DocumentDisplays.xml — inactive document-display config.

Marked ``INACTIVE`` in the XSD. Each display picks exactly one source:
report, compose, or browser; each carries an optional relativeViewPeriod.

The XSD outer choice is permissive — it allows an empty display (no
source at all) — so the Pydantic model leaves all three source fields
optional without an exactly-one validator.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel, RelativePeriod


ProductProperty = Literal["timeZero", "sourceId", "areaId"]


class DocumentDisplayShowReport(FewsModel):
    productWorkflowStatusId: list[str] = Field(default_factory=list)


class DocumentDisplayReport(FewsModel):
    archiveProductId: str | None = None
    reportModuleInstanceId: str | None = None
    showReports: DocumentDisplayShowReport | None = None
    editor: bool | None = None


class DocumentDisplayCompose(FewsModel):
    composeId: list[str] = Field(default_factory=list)


class DocumentDisplayHeader(FewsModel):
    """simpleContent — text body plus attributes."""

    value: str
    name: str
    productProperty: ProductProperty | None = None
    productAttribute: str | None = None


class DocumentDisplayBrowserLayoutHeaders(FewsModel):
    header: list[DocumentDisplayHeader] = Field(min_length=1)


class DocumentDisplayBrowserLayout(FewsModel):
    preview: bool | None = None
    headers: DocumentDisplayBrowserLayoutHeaders | None = None


class DocumentDisplayBrowserArchiveProducts(FewsModel):
    archiveProductId: list[str] = Field(default_factory=list)
    archiveProductSetId: list[str] = Field(default_factory=list)


class DocumentDisplayBrowser(FewsModel):
    archiveProducts: DocumentDisplayBrowserArchiveProducts
    layout: DocumentDisplayBrowserLayout | None = None


class DocumentDisplay(FewsModel):
    id: str
    name: str
    report: DocumentDisplayReport | None = None
    compose: DocumentDisplayCompose | None = None
    browser: DocumentDisplayBrowser | None = None
    relativeViewPeriod: RelativePeriod | None = None
    viewPermission: str | None = None
    editPermission: str | None = None


class DocumentDisplays(FewsModel):
    documentDisplay: list[DocumentDisplay] = Field(min_length=1)
