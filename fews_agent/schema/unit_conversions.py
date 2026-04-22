"""UnitConversions (Import/Export/ExportRaven).xml — unit conversion tables.

Referenced by ImportModule.unitConversionsId and ModelRunModule.unitConversionsId.
The file's own id comes from its filename (convention).
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class UnitConversion(FewsModel):
    # multiplier/incrementer are str (not float or Decimal) to preserve the
    # exact source representation. Tutorial values include integers (86400),
    # short decimals (0.5556), and scientific notation (2.77777E-4) — none
    # of which survive float or Decimal round-trip under :f formatting.
    inputUnitType: str
    outputUnitType: str
    multiplier: str | None = None
    incrementer: str | None = None


class UnitConversions(FewsModel):
    """Root of a UnitConversions file."""

    unitConversion: list[UnitConversion] = Field(min_length=1)
