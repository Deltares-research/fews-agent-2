"""CorrelationEventSets.xml — observed historical events keyed by
location (inline) or by location-set attribute mapping.

XSD inner choice for CorrelationEventSet: either an inline
(locationId + parameterId + event[]) sequence, or a locationSet-based
attribute-mapping sequence. Modelled as two optional blocks with a
validator enforcing exactly-one.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import Field, model_validator

from .common import FewsModel


class CorrelationEvent(FewsModel):
    value: Decimal
    date: str
    eventId: str | None = None
    time: str | None = None
    tag: str | None = None
    tag1: str | None = None
    tag2: str | None = None
    tag3: str | None = None
    tag4: str | None = None
    comment: str | None = None


class InlineCorrelationEventSet(FewsModel):
    locationId: str
    parameterId: str
    event: list[CorrelationEvent] = Field(min_length=1)


class AttrMappedCorrelationEventSet(FewsModel):
    locationSetId: str
    eventIdAttributeId: str
    eventParameterLocationAttributeId: str
    eventTimeLocationAttributeId: str
    eventValueLocationAttributeId: str
    eventTagLocationAttributeId: list[str] = Field(default_factory=list)
    eventCommentLocationAttributeId: str | None = None


class CorrelationEventSet(FewsModel):
    """XSD choice between the two forms."""

    inline: InlineCorrelationEventSet | None = None
    attrMapped: AttrMappedCorrelationEventSet | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> CorrelationEventSet:
        if (self.inline is None) == (self.attrMapped is None):
            raise ValueError(
                "correlationEventSet: supply exactly one of inline or attrMapped"
            )
        return self


class CorrelationEventSets(FewsModel):
    """Root of CorrelationEventSets.xml."""

    timeZone: str | None = None
    correlationEventSet: list[CorrelationEventSet] = Field(min_length=1)
    comment: str | None = None
