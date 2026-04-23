"""Polygons.xml — ESRI shapefile mappings to FEWS locations."""
from __future__ import annotations

from decimal import Decimal

from pydantic import Field, model_validator

from .common import FewsModel
from .ids import LocationId


class EsriShape(FewsModel):
    locationId: LocationId | None = None
    shapeId: str | None = None


class EsriShapeFile(FewsModel):
    """One shapefile. Exactly one of shape[] / shapeIdFunction is required."""

    file: str
    geoDatum: str
    shapeIdAttributeName: str
    areaAttributeName: str | None = None
    # areaMultiplier preserved as Decimal so "1" doesn't become "1.0".
    areaMultiplier: Decimal | None = None
    shape: list[EsriShape] = Field(default_factory=list)
    shapeIdFunction: str | None = None

    @model_validator(mode="after")
    def _shape_xor_function(self) -> EsriShapeFile:
        has_shapes = len(self.shape) > 0
        has_fn = self.shapeIdFunction is not None
        if has_shapes == has_fn:
            raise ValueError(
                "esriShapeFile: supply either shape[] or shapeIdFunction (not both)"
            )
        return self


class Polygons(FewsModel):
    """Root of Polygons.xml. At least one esriShapeFile required."""

    esriShapeFile: list[EsriShapeFile] = Field(min_length=1)
