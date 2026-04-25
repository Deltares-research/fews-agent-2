"""Locations.xml — declares locationId used across the config.

Full LocationComplexType coverage: description, shortName, label,
toolTip, parentLocationId, visibilityPeriod (DateTime pair),
x/y/z/bedLevel, layerSigmaCoordinate, plus the id/name attributes.

XSD's ``AttributeChoice`` group is NOT modelled here — it uses
namespace-any with three runtime namespaces (numberAttribute /
textAttribute / booleanAttribute), which doesn't map to typed
Pydantic fields. Callers who need custom attributes declare them at
the LocationSet / Parameter / Qualifier level instead, or use the
GenericXmlFile passthrough for an edge case.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from .archive_metadata import DateTimePair
from .common import FewsModel
from .ids import LocationId


class LocationVisibilityPeriod(FewsModel):
    """Optional visibility window using DateTime (date + optional time)."""

    startDateTime: DateTimePair | None = None
    endDateTime: DateTimePair | None = None


class Location(FewsModel):
    # Decimal (not float) preserves the exact numeric representation from
    # the JSON source. Integer JSON values emit as "-180" (not "-180.0"),
    # and long decimals like 0.00000000000000000001 survive intact. Required
    # for C14N equality against hand-authored XML.
    id: LocationId
    name: str
    x: Decimal
    y: Decimal
    description: str | None = None
    shortName: str | None = None
    label: str | None = None
    toolTip: str | None = None
    parentLocationId: LocationId | None = None
    visibilityPeriod: LocationVisibilityPeriod | None = None
    z: Decimal | None = None
    bedLevel: Decimal | None = None
    # sigmaCoordinateDouble is a restricted double (0..1); left as Decimal
    # for the same source-preservation reason.
    layerSigmaCoordinate: Decimal | None = None


class Locations(FewsModel):
    """Root of Locations.xml.

    ``timeZone`` is optional — if absent, FEWS defaults to GMT.
    """

    geoDatum: str
    location: list[Location] = Field(min_length=1)
    timeZone: str | None = None
    version: str = "1.1"
