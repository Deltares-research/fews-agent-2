"""LocationIcons.xml — icon-to-locationSet mapping for the map view."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel
from .ids import LocationSetId


class LocationIcon(FewsModel):
    iconId: str
    locationSetId: LocationSetId
    description: str | None = None


class LocationIcons(FewsModel):
    locationIcon: list[LocationIcon] = Field(min_length=1)
    rootDir: str | None = None
