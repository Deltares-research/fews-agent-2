"""Locations.xml — declares locationId used across the config."""
from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from .common import FewsModel
from .ids import LocationId


class LocationAttribute(FewsModel):
    key: str
    value: str


class Location(FewsModel):
    # Decimal (not float) preserves the exact numeric representation from
    # the JSON source. Integer JSON values emit as "-180" (not "-180.0"),
    # and long decimals like 0.00000000000000000001 survive intact. Required
    # for C14N equality against hand-authored XML.
    id: LocationId
    name: str
    x: Decimal
    y: Decimal
    shortName: str | None = None
    description: str | None = None
    z: Decimal | None = None
    parentLocationId: LocationId | None = None
    relation: str | None = None
    attribute: list[LocationAttribute] = Field(default_factory=list)


class Locations(FewsModel):
    """Root of Locations.xml."""

    geoDatum: str
    location: list[Location] = Field(min_length=1)
    version: str = "1.1"
