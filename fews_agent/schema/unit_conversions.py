"""UnitConversions (Import/Export/ExportRaven).xml — unit conversion tables.

Referenced by ImportModule.unitConversionsId and ModelRunModule.unitConversionsId.
The file's own id comes from its filename (convention).
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class UnitConversion(FewsModel):
    inputUnitType: str
    outputUnitType: str
    multiplier: float | None = None
    incrementer: float | None = None


class UnitConversions(FewsModel):
    """Root of a UnitConversions file."""

    unitConversion: list[UnitConversion] = Field(min_length=1)
