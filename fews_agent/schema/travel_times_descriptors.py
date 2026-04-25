"""TravelTimesDescriptors.xml — registry of available TravelTimes files.

Note: unlike the other *Descriptors files, this XSD has no `version` attr.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class TravelTimesDescriptor(FewsModel):
    id: str
    name: str | None = None
    description: str | None = None


class TravelTimesDescriptors(FewsModel):
    """Root of TravelTimesDescriptors.xml."""

    travelTimesDescriptor: list[TravelTimesDescriptor] = Field(min_length=1)
