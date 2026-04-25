"""Transformations.xml — regional lookup-table transformations.

Distinct from ``fews_agent.schema.transformation_module.TransformationModule``
(the full transformation module config); this is the lightweight
region-level <transformations> registry with period-dependent table
rewrites.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from .common import FewsModel


class TransformationTableRecord(FewsModel):
    input: Decimal
    output: Decimal


class TransformationTable(FewsModel):
    tableRecord: list[TransformationTableRecord] = Field(min_length=1)


class TransformationValidPeriod(FewsModel):
    startDate: str | None = None
    endDate: str | None = None


class PeriodDependantTransformation(FewsModel):
    validPeriod: list[TransformationValidPeriod] = Field(default_factory=list)
    table: TransformationTable


class TransformationEntry(FewsModel):
    id: str
    name: str | None = None
    periodDependantTransformation: list[PeriodDependantTransformation] = Field(min_length=1)


class Transformations(FewsModel):
    """Root of Transformations.xml."""

    transformation: list[TransformationEntry] = Field(min_length=1)
    version: str = "1.1"
