"""StorageBasinSystem.xml — storage basin with elevation/storage curves
and pumping stations.

XSD root element is `<storageBasin>` (singular). `StructureComplexType`
is a single-variant <choice> today (only <pumpingStation>); future
XSD revisions could add gates/weirs/sluices, so the structure element
stays a named wrapper in the model.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from .common import FewsModel


class ElevationStorageTableEntry(FewsModel):
    """One row of the elevation-storage curve (stage/area/outflow optional)."""

    elevation: Decimal
    storage: Decimal
    stage: Decimal | None = None
    area: Decimal | None = None
    outflowDischarge: Decimal | None = None


class ConstantDischarge(FewsModel):
    discharge: Decimal
    description: str | None = None


class PumpState(FewsModel):
    id: int
    constantDischarge: ConstantDischarge


class PumpingStation(FewsModel):
    id: str
    name: str | None = None
    minimumDeploymentTime: int | None = None
    switchOfLevel: Decimal | None = None
    switchOnLevel: Decimal | None = None
    alarmLevel: Decimal | None = None
    pumpState: list[PumpState] = Field(min_length=1)


class Structure(FewsModel):
    """XSD choice wrapper — exactly one structure kind per element."""

    pumpingStation: PumpingStation


class StorageBasinSystem(FewsModel):
    """Root of StorageBasin.xml (XSD root element: <storageBasin>)."""

    id: str
    name: str | None = None
    elevationStorageTable: list[ElevationStorageTableEntry] = Field(min_length=1)
    structure: list[Structure] = Field(min_length=1)
