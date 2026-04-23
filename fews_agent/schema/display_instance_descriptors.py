"""DisplayInstanceDescriptors.xml — instance-level variants referencing
a displayId from DisplayDescriptors."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class DisplayInstanceDescriptor(FewsModel):
    id: str
    name: str | None = None
    description: str | None = None
    displayId: str


class DisplayInstanceDescriptors(FewsModel):
    """Root of DisplayInstanceDescriptors.xml."""

    displayInstanceDescriptor: list[DisplayInstanceDescriptor] = Field(min_length=1)
    version: str = "1.0"
