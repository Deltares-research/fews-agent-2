"""ModuleDescriptors.xml — registry mapping module ids to Java classes."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class ModuleDescriptor(FewsModel):
    id: str
    name: str | None = None
    description: str | None = None
    className: str


class ModuleDescriptors(FewsModel):
    """Root of ModuleDescriptors.xml."""

    moduleDescriptor: list[ModuleDescriptor] = Field(min_length=1)
    version: str = "1.0"
