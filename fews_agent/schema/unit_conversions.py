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
    #
    # XSD requires both `multiplier` and `incrementer` (no minOccurs="0"),
    # though it specifies defaults of 1 and 0 respectively. Pydantic
    # mirrors that by giving each a sentinel default rather than allowing
    # them to be omitted entirely (which would emit XSD-invalid output).
    inputUnitType: str
    outputUnitType: str
    multiplier: str = "1"
    incrementer: str = "0"
    # Optional per-conversion datum flag: convert from/to Ordnance level on
    # import/export. XSD-default false; modeled optional so it only renders
    # when supplied.
    convertDatum: bool | None = None


class UnitConversions(FewsModel):
    """Root of a UnitConversions file."""

    # Optional root flag (XSD-default false): when true, FEWS also registers
    # the inverse of every listed conversion. Precedes the conversion list.
    addInverses: bool | None = None
    unitConversion: list[UnitConversion] = Field(min_length=1)
