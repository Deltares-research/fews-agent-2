"""Qualifiers.xml — declares qualifierId (mean, max, min, 25%, 75%, ...).

Previously the ``shortName`` and ``group`` fields were rendered as
attributes — the XSD defines them as child elements. Fixed here; also
adds the missing ``description`` child and the recursive ``child``
qualifier list.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel
from .ids import QualifierId


class Qualifier(FewsModel):
    """Recursive: a qualifier can have nested ``<child>`` qualifiers of
    the same type."""

    id: QualifierId
    name: str | None = None
    description: str | None = None
    shortName: str | None = None
    group: str | None = None
    child: "list[Qualifier]" = Field(default_factory=list)


Qualifier.model_rebuild()


class QualifiersCsvFile(FewsModel):
    """Since 2022.01 — load qualifier definitions from a CSV file in lieu
    of inline ``<qualifier>`` entries."""

    file: str
    charset: str | None = None


class QualifierNode(FewsModel):
    """XSD QualifierNodeComplexType — root of the optional qualifier
    tree hierarchy (UI grouping). Recursive: can contain child
    qualifierNode entries under the same complex type, plus qualifierId
    references and attribute-driven constraints."""

    id: str
    name: str | None = None
    description: str | None = None
    qualifierId: list[str] = Field(default_factory=list)
    qualifierNode: "list[QualifierNode]" = Field(default_factory=list)
    constraints: list[dict[str, Any]] = Field(default_factory=list)


QualifierNode.model_rebuild()


class Qualifiers(FewsModel):
    """Root of Qualifiers.xml. Supports inline ``<qualifier>`` entries,
    CSV sources, and an optional root node for UI hierarchy — all
    mutually optional (at least one of qualifier / csvFile is expected).
    """

    qualifier: list[Qualifier] = Field(default_factory=list)
    csvFile: list[QualifiersCsvFile] = Field(default_factory=list)
    qualifierRootNode: QualifierNode | None = None
    allowReferencingUndefinedQualifiers: bool = False
