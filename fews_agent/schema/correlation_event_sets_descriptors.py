"""CorrelationEventSetsDescriptors.xml — registry of available CorrelationEventSets files.

Note: like TravelTimesDescriptors, this XSD has no `version` attr.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class CorrelationEventSetsDescriptor(FewsModel):
    id: str
    name: str | None = None
    description: str | None = None


class CorrelationEventSetsDescriptors(FewsModel):
    """Root of CorrelationEventSetsDescriptors.xml."""

    correlationEventSetsDescriptor: list[CorrelationEventSetsDescriptor] = Field(min_length=1)
