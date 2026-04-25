"""ValueAttributeMaps.xml — maps time-series values to displayable
attributes (description/colour/image)."""
from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from .common import FewsModel


class ValueAttributes(FewsModel):
    """`<attributes value="...">` — one row of the value→attributes map."""

    value: Decimal
    description: str
    colour: str | None = None
    image: str | None = None


class ValueAttributeMap(FewsModel):
    id: str
    attributes: list[ValueAttributes] = Field(min_length=1)


class ValueAttributeMaps(FewsModel):
    """Root of ValueAttributeMaps.xml."""

    valueAttributeMap: list[ValueAttributeMap] = Field(min_length=1)
    version: str = "1.0"
