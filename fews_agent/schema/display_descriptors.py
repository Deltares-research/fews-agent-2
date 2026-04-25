"""DisplayDescriptors.xml — registry mapping display ids to Java classes."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class DisplayDescriptor(FewsModel):
    id: str
    name: str | None = None
    description: str | None = None
    className: str


class DisplayDescriptors(FewsModel):
    """Root of DisplayDescriptors.xml."""

    displayDescriptor: list[DisplayDescriptor] = Field(min_length=1)
    version: str = "1.0"
