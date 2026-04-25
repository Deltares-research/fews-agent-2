"""Documents.xml — archive/compose/product catalog (Region chapter 36).

Models the four top-level children of `<documents>`: documentWorkflow
(status + transition state machine), archiveProduct (defines a
versioned product from an area/source), composeProduct (composes
several archiveProducts), and archiveProductSet (selects products by
attribute constraints).

XSD order matters: sequence is documentWorkflow, archiveProduct,
composeProduct, archiveProductSet. All four are 0..unbounded, so an
empty <documents/> is valid.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class DocumentAttribute(FewsModel):
    key: str
    value: str


class Status(FewsModel):
    id: str
    name: str
    default: bool | None = None
    attribute: DocumentAttribute


class Transition(FewsModel):
    fromStatus: str
    toStatus: str
    editPermission: str


class DocumentWorkflow(FewsModel):
    id: str
    status: list[Status] = Field(min_length=1)
    transition: list[Transition] = Field(default_factory=list)


class ArchiveProduct(FewsModel):
    id: str
    name: str
    documentWorkflowId: str | None = None
    areaId: str
    sourceId: str
    versionKey: list[str] = Field(default_factory=list)
    attribute: list[DocumentAttribute] = Field(default_factory=list)


class ComposeProductTemplate(FewsModel):
    archiveProductId: str


class ComposeProduct(FewsModel):
    # XSD declares id and name as attributes without use="required".
    id: str | None = None
    name: str | None = None
    archiveProductId: str
    template: ComposeProductTemplate


class AttributeTextEquals(FewsModel):
    id: str
    equals: str


class ArchiveProductSetValidation(FewsModel):
    """Wraps <allValid>/<anyValid> — XSD requires 1+ attributeTextEquals."""

    attributeTextEquals: list[AttributeTextEquals] = Field(min_length=1)


class ArchiveProductSetConstraints(FewsModel):
    areaId: str
    sourceId: str | None = None
    allValid: ArchiveProductSetValidation | None = None
    anyValid: ArchiveProductSetValidation | None = None


class ArchiveProductSet(FewsModel):
    id: str
    constraints: ArchiveProductSetConstraints


class Documents(FewsModel):
    """Root of Documents.xml."""

    documentWorkflow: list[DocumentWorkflow] = Field(default_factory=list)
    archiveProduct: list[ArchiveProduct] = Field(default_factory=list)
    composeProduct: list[ComposeProduct] = Field(default_factory=list)
    archiveProductSet: list[ArchiveProductSet] = Field(default_factory=list)
