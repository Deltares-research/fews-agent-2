"""GribTimeSeriesReader.xml — legacy grib record mapping.

One ``<recordDefinition>`` per (parameterId, levelId) pair; attribute-only.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class GribRecordDefinition(FewsModel):
    parameterId: str
    levelId: str


class GribTimeSeriesReader(FewsModel):
    recordDefinition: list[GribRecordDefinition] = Field(min_length=1)
