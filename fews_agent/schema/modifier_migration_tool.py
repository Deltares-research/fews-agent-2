"""ModifierMigrationTool.xml — batch-migrate modifier values across
locations/sets to a new attribute."""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel


class LocationAttributeModifierMigration(FewsModel):
    """XSD choice: locationId OR locationSetId, not both."""

    locationId: str | None = None
    locationSetId: str | None = None
    modifierId: str
    attribute: str

    @model_validator(mode="after")
    def _loc_xor_set(self) -> LocationAttributeModifierMigration:
        has_loc = self.locationId is not None
        has_set = self.locationSetId is not None
        if has_loc == has_set:
            raise ValueError(
                "locationAttributeMigration: supply exactly one of locationId or locationSetId"
            )
        return self


class ModifierMigrationTool(FewsModel):
    """Root of ModifierMigrationTool.xml."""

    locationAttributeMigration: list[LocationAttributeModifierMigration] = Field(min_length=1)
