"""LocationIcons.xml — icon-to-locationSet mapping for the map view."""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel
from .ids import LocationId, LocationSetId


class LocationIcon(FewsModel):
    """XSD choice: ``locationId[]`` XOR ``locationSetId`` (one required)."""

    iconId: str
    locationSetId: LocationSetId | None = None
    locationId: list[LocationId] = Field(default_factory=list)
    description: str | None = None

    @model_validator(mode="after")
    def _one_target(self) -> LocationIcon:
        if bool(self.locationId) == (self.locationSetId is not None):
            raise ValueError(
                "locationIcon: supply exactly one of locationSetId or "
                "locationId[]"
            )
        return self


class LocationIcons(FewsModel):
    locationIcon: list[LocationIcon] = Field(min_length=1)
    rootDir: str | None = None
