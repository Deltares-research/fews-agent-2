"""UnreferencedNcFilesCleaner.xml — deletes orphaned netCDF files
under configured roots after a minimum age."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel, UnitMultiplier


class NcRootDir(FewsModel):
    urlPrefix: str
    path: str


class UnreferencedNcFilesCleaner(FewsModel):
    """Root of UnreferencedNcFilesCleaner.xml. XSD uses TimeSpanComplexType
    for minimalAgeNcFile, which allows multiplier=0 (the snippet's usage)
    — so UnitMultiplier not TimeStep."""

    minimalAgeNcFile: UnitMultiplier
    rootDir: list[NcRootDir] = Field(min_length=1)
