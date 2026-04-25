"""ExportArchiveModule.xml — module config for archive exports.

XSD root: ``exportArchiveModule`` (ExportArchiveModuleComplexType).

Top-level shape: a single ``<choice maxOccurs="unbounded">`` over 16
distinct export-activity element names:
  exportSimulated, exportSimulatedHistorical, exportObserved,
  exportExternalForecast, exportMessages, exportRatingCurves,
  exportConfig, exportSnapShot, exportProducts, amalgamateObserved,
  mergeEditedObservedData,
  exportExternalHistoricalTimeSeriesToArchiveDatabase,
  exportSimulatedTimeSeriesToArchiveDatabase,
  exportExternalForecastingTimeSeriesToArchiveDatabase,
  migrateOpenArchiveToArchiveDatabase, copyArchivedData.

Sibling order may matter (the XSD ``choice`` permits any sequence).
We model the body as a list of single-key dicts — same pattern used
for Grids.xml's interleaved <regular>/<irregular>. Each entry's key
is the activity element name; the value is a ``dict[str, Any]`` body
with an optional ``@id`` attribute (each activity carries an idStringType
attribute by XSD inheritance).

Each activity body is itself deeply nested (general settings group,
attributes lists, source files, time-zero formatting, ...). Per
CLAUDE.md "``dict[str, Any]`` for subtrees deeper than 3 nesting
levels" we keep each activity as a passthrough dict.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel


class ExportArchiveModule(FewsModel):
    """Root of ExportArchiveModule.xml.

    ``activities`` preserves declared order across the 16 heterogeneous
    activity element kinds. Each entry is a single-key dict.
    """

    activities: list[dict[str, Any]] = Field(min_length=1)
