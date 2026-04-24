"""MassBalance.xml — slices an area from a grid and computes net volume.

XSD root is a ``choice maxOccurs="unbounded"`` over five slice-activity
element types. We model each kind as its own list on ``MassBalance``
and emit them in a fixed order; XSD accepts any order within the
unbounded choice so this stays schema-valid for any mix.

The two vertical variants (``SliceVerticalFlux`` / ``SliceVerticalVelocity``)
carry an inner XSD choice: either the upper+lower face pair OR a
single net-face series. Enforced via ``model_validator``.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel, TimeSeriesSet


class SliceHorizontalFlux(FewsModel):
    uFluxFieldTimeSeriesSet: TimeSeriesSet
    vFluxFieldTimeSeriesSet: TimeSeriesSet
    outputTimeSeriesSet: TimeSeriesSet
    multiplyByCellSize: bool | None = None
    staggeredGrid: bool | None = None
    invertedYDirection: bool | None = None


class SliceHorizontalVelocity(FewsModel):
    uVelocityFieldTimeSeriesSet: TimeSeriesSet
    vVelocityFieldTimeSeriesSet: TimeSeriesSet
    outputTimeSeriesSet: TimeSeriesSet
    staggeredGrid: bool | None = None
    invertedYDirection: bool | None = None


class SliceVerticalFlux(FewsModel):
    """Either upperFaceFluxFieldTimeSeriesSet + lowerFaceFluxFieldTimeSeriesSet
    XOR netVertFluxFieldTimeSeriesSet (XSD choice)."""

    outputTimeSeriesSet: TimeSeriesSet
    upperFaceFluxFieldTimeSeriesSet: TimeSeriesSet | None = None
    lowerFaceFluxFieldTimeSeriesSet: TimeSeriesSet | None = None
    netVertFluxFieldTimeSeriesSet: TimeSeriesSet | None = None

    @model_validator(mode="after")
    def _one_flux_branch(self) -> SliceVerticalFlux:
        pair = (self.upperFaceFluxFieldTimeSeriesSet, self.lowerFaceFluxFieldTimeSeriesSet)
        has_pair = any(x is not None for x in pair)
        has_net = self.netVertFluxFieldTimeSeriesSet is not None
        if has_pair and has_net:
            raise ValueError(
                "verticalFlux: choose upper+lower face OR net-face flux, not both"
            )
        if has_pair and not all(x is not None for x in pair):
            raise ValueError(
                "verticalFlux: upperFaceFluxFieldTimeSeriesSet and "
                "lowerFaceFluxFieldTimeSeriesSet must be supplied together"
            )
        if not has_pair and not has_net:
            raise ValueError(
                "verticalFlux: supply upper+lower face pair OR netVertFluxFieldTimeSeriesSet"
            )
        return self


class SliceVerticalVelocity(FewsModel):
    """upperFaceVelocityFieldTimeSeriesSet + lowerFaceVelocityFieldTimeSeriesSet
    XOR netVertVelocityFieldTimeSeriesSet (XSD choice)."""

    outputTimeSeriesSet: TimeSeriesSet
    upperFaceVelocityFieldTimeSeriesSet: TimeSeriesSet | None = None
    lowerFaceVelocityFieldTimeSeriesSet: TimeSeriesSet | None = None
    netVertVelocityFieldTimeSeriesSet: TimeSeriesSet | None = None

    @model_validator(mode="after")
    def _one_velocity_branch(self) -> SliceVerticalVelocity:
        pair = (
            self.upperFaceVelocityFieldTimeSeriesSet,
            self.lowerFaceVelocityFieldTimeSeriesSet,
        )
        has_pair = any(x is not None for x in pair)
        has_net = self.netVertVelocityFieldTimeSeriesSet is not None
        if has_pair and has_net:
            raise ValueError(
                "verticalVelocity: choose upper+lower face OR net-face velocity, "
                "not both"
            )
        if has_pair and not all(x is not None for x in pair):
            raise ValueError(
                "verticalVelocity: upperFaceVelocityFieldTimeSeriesSet and "
                "lowerFaceVelocityFieldTimeSeriesSet must be supplied together"
            )
        if not has_pair and not has_net:
            raise ValueError(
                "verticalVelocity: supply upper+lower face pair OR "
                "netVertVelocityFieldTimeSeriesSet"
            )
        return self


class SliceStorageChange(FewsModel):
    """Choice: waterTableChangeTimeSeriesSet XOR storageChangeFluxFieldTimeSeriesSet."""

    outputTimeSeriesSet: TimeSeriesSet
    multiplyByCellSize: bool | None = None
    waterTableChangeTimeSeriesSet: TimeSeriesSet | None = None
    storageChangeFluxFieldTimeSeriesSet: TimeSeriesSet | None = None

    @model_validator(mode="after")
    def _one_storage_branch(self) -> SliceStorageChange:
        has_wt = self.waterTableChangeTimeSeriesSet is not None
        has_sc = self.storageChangeFluxFieldTimeSeriesSet is not None
        if has_wt == has_sc:
            raise ValueError(
                "storageChange: supply exactly one of waterTableChangeTimeSeriesSet "
                "or storageChangeFluxFieldTimeSeriesSet"
            )
        return self


class MassBalance(FewsModel):
    horizontalFlux: list[SliceHorizontalFlux] = Field(default_factory=list)
    horizontalVelocity: list[SliceHorizontalVelocity] = Field(default_factory=list)
    verticalFlux: list[SliceVerticalFlux] = Field(default_factory=list)
    verticalVelocity: list[SliceVerticalVelocity] = Field(default_factory=list)
    storageChange: list[SliceStorageChange] = Field(default_factory=list)

    @model_validator(mode="after")
    def _at_least_one_activity(self) -> MassBalance:
        if not any(
            [
                self.horizontalFlux,
                self.horizontalVelocity,
                self.verticalFlux,
                self.verticalVelocity,
                self.storageChange,
            ]
        ):
            raise ValueError("massBalance: supply at least one activity entry")
        return self
