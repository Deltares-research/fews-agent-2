"""ImportRun.xml — configuration for the import module.

One or more ``<import>`` entries, each describing a folder to poll,
the idMap / unitConversions / flagConversions to apply, and the
timeSeriesSets to populate.

The XSD root is ``<importRun>``. Distinct from the Import module
config (TimeSeriesImportRun / ``<timeSeriesImportRun>``) already handled
in import_module.py — the importRun format is the legacy-style single
module config for telemetry/dds/harp/hyrad-k imports.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel, RelativeViewPeriod, TimeSeriesSet, TimeZone


ImportType = Literal["telemetry", "dds", "harp", "hyrad-k"]


class TimeStampTolerance(FewsModel):
    """`<tolerance/>` — all attributes bar the optional location fields
    are required. `unitCount` is an int per XSD."""

    parameterId: str
    timeUnit: str
    unitCount: int
    locationSetId: str | None = None
    locationId: str | None = None


class StartTimeShift(FewsModel):
    """`<startTimeShift>` — location+parameter pair with a relative period."""

    locationId: str
    parameterId: str
    relativePeriod: RelativeViewPeriod


class ImportEntry(FewsModel):
    folder: str
    failedFolder: str | None = None
    backupFolder: str | None = None
    validate_: bool | None = Field(default=None, alias="validate")
    idMapId: str | None = None
    unitConversionsId: str | None = None
    flagConversionsId: str | None = None
    tolerance: list[TimeStampTolerance] = Field(default_factory=list)
    startTimeShift: list[StartTimeShift] = Field(default_factory=list)
    timeSeriesSet: list[TimeSeriesSet] = Field(min_length=1)
    importType: ImportType | None = None
    importTimeZone: TimeZone | None = None
    dataFeedId: str | None = None
    missingValue: list[float] = Field(default_factory=list)
    traceValue: list[float] = Field(default_factory=list)


class ImportRun(FewsModel):
    """Root of ``<importRun>``."""

    import_: list[ImportEntry] = Field(min_length=1, alias="import")
