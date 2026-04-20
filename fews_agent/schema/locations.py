"""Locations.xml — declares locationId used across the config."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel
from .ids import LocationId


class LocationAttribute(FewsModel):
    key: str
    value: str


class Location(FewsModel):
    id: LocationId
    name: str
    x: float
    y: float
    shortName: str | None = None
    description: str | None = None
    z: float | None = None
    parentLocationId: LocationId | None = None
    relation: str | None = None
    attribute: list[LocationAttribute] = Field(default_factory=list)


class Locations(FewsModel):
    """Root of Locations.xml."""

    geoDatum: str
    location: list[Location] = Field(min_length=1)
    version: str = "1.1"
