"""FlagConversionsDescriptors.xml — registry of available FlagConversions files."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class FlagConversionsDescriptor(FewsModel):
    id: str
    name: str | None = None
    description: str | None = None


class FlagConversionsDescriptors(FewsModel):
    """Root of FlagConversionsDescriptors.xml."""

    flagConversionsDescriptor: list[FlagConversionsDescriptor] = Field(min_length=1)
    version: str = "1.0"
