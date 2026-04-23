"""WapdaTimeSeriesReader.xml — column-based reader for WAPDA (Pakistan
Water and Power Development Authority) CSV/tabular imports."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class WapdaColumnDefinition(FewsModel):
    locationId: str
    parameterId: str
    column: int


class WapdaTimeSeriesReader(FewsModel):
    """Root of WapdaTimeSeriesReader.xml."""

    columnDefinition: list[WapdaColumnDefinition] = Field(min_length=1)
