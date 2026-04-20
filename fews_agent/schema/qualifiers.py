"""Qualifiers.xml — declares qualifierId (mean, max, min, 25%, 75%, ...)."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel
from .ids import QualifierId


class Qualifier(FewsModel):
    id: QualifierId
    name: str | None = None
    group: str | None = None
    shortName: str | None = None


class Qualifiers(FewsModel):
    """Root of Qualifiers.xml."""

    qualifier: list[Qualifier] = Field(min_length=1)
    allowReferencingUndefinedQualifiers: bool = False
