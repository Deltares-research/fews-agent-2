"""FlagConversions.xml — converts external flag values (strings) to
internal FEWS integer flags."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class FlagInt(FewsModel):
    """Internal FEWS flag: integer value."""

    value: int
    name: str | None = None
    description: str | None = None


class FlagString(FewsModel):
    """External flag: string value."""

    value: str
    name: str | None = None
    description: str | None = None


class FlagConversion(FewsModel):
    inputFlag: FlagString
    outputFlag: FlagInt


class FlagConversions(FewsModel):
    """Root of FlagConversions.xml.

    XSD: missingValueFlag required; flagConversion[] + defaultOuputFlag
    (sic: XSD spells it defaultOuputFlag with one 't') are optional.
    """

    flagConversion: list[FlagConversion] = Field(default_factory=list)
    defaultOuputFlag: FlagInt | None = None
    missingValueFlag: FlagInt
