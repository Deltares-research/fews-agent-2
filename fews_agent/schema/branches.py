"""Branches.xml — river branches with chainage and point geometry."""
from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from .common import FewsModel


class BranchNodePoint(FewsModel):
    """Per-chainage cross-section point with optional z-levels.

    All 9 z-* attributes plus x/y are optional per XSD; only chainage
    and label are required.
    """

    chainage: Decimal
    label: str
    x: Decimal | None = None
    y: Decimal | None = None
    z: Decimal | None = None
    z_lmc: Decimal | None = None
    z_rmc: Decimal | None = None
    z_lb: Decimal | None = None
    z_rb: Decimal | None = None
    z_lfp: Decimal | None = None
    z_rfp: Decimal | None = None
    description: str | None = None
    thresholdValueSetId: str | None = None


class Branch(FewsModel):
    id: str
    branchName: str
    startChainage: Decimal
    endChainage: Decimal
    pt: list[BranchNodePoint] = Field(min_length=2)
    upNode: str | None = None
    downNode: str | None = None
    zone: str | None = None
    comment: str | None = None


class Branches(FewsModel):
    """Root of Branches.xml."""

    geoDatum: str
    branch: list[Branch] = Field(min_length=1)
    version: str = "1.1"
