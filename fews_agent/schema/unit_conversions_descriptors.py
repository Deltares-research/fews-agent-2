"""UnitConversionsDescriptors.xml — registry of available UnitConversions files."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class UnitConversionsDescriptor(FewsModel):
    id: str
    name: str | None = None
    description: str | None = None


class UnitConversionsDescriptors(FewsModel):
    """Root of UnitConversionsDescriptors.xml."""

    unitConversionsDescriptor: list[UnitConversionsDescriptor] = Field(min_length=1)
    version: str = "1.0"
