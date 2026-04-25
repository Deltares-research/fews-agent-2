"""TimeSeriesExportRun.xml — module config for time-series exporters.

XSD root: ``timeSeriesExportRun``. Contains 1..n ``export`` entries.

Each ``export`` (TimeSeriesExportRunComplexType) is structurally:
  - ``general`` (TimeSeriesExportGeneralComplexType — tens of fields with
    nested choices: serializer, folder/serverUrl, idMapId, missingValue,
    timeZone, datafeed, ...)
  - optional ``properties``
  - optional ``metadata``
  - 0..n ``exportAttribute`` entries
  - 0..n ``exportLocationAttributeAsNetCDFVariable`` entries
  - optional ``exportArchiveMetadata`` boolean
  - choice 0..n: timeSeriesSet | timeSeriesSets | filterId | annotationLocationSetId

Per CLAUDE.md "``dict[str, Any]`` for subtrees deeper than 3 nesting
levels", we keep each ``export`` body as a single pass-through dict.
The dict's keys map to XSD-sequence element names. Caller honours
order; XSD validates.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel


class TimeSeriesExportRun(FewsModel):
    """Root of TimeSeriesExportRun.xml.

    Each entry in ``export`` is a pass-through dict whose keys are the
    XSD child element names (general, properties, metadata,
    exportAttribute, ..., timeSeriesSet/timeSeriesSets/filterId/
    annotationLocationSetId). Repeated children may be expressed as
    lists.
    """

    export: list[dict[str, Any]] = Field(min_length=1)
