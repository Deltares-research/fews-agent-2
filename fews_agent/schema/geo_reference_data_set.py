"""GeoReferenceDataSet.xml — legacy geo-reference labels for flood map sections.

Marked ``LEGACY, NO LONGER USED`` in the XSD but still schema-valid.
Ties a label id to a ``mapSectionId`` plus one or more (x, y) points.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field

from .common import FewsModel


class GeoReferenceDataPoint(FewsModel):
    """XSD PointComplexType — both ``x`` and ``y`` are optional."""

    x: Decimal | None = None
    y: Decimal | None = None


class GeoReferenceData(FewsModel):
    label: str
    mapSectionId: int
    point: list[GeoReferenceDataPoint] = Field(min_length=1)


class GeoReferenceDataSet(FewsModel):
    """Fixed ``version="1.1"`` attribute; emitted by the template."""

    geoDatum: str
    geoReferenceData: list[GeoReferenceData] = Field(min_length=1)
    version: Literal["1.1"] = "1.1"
