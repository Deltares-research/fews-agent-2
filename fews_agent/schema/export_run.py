"""ExportRun.xml — inactive export-module config.

Marked ``INACTIVE`` in the XSD. Each ``<export>`` entry wires a folder
destination to a set of timeSeriesSets plus optional idMap / unit /
flag conversions and time-zone settings.

``validate`` is a Python keyword, so the Pydantic field is named
``validate_`` (alias ``validate``) and templates must use the suffixed
field name — ``model_dump`` emits field names, not aliases.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from .common import FewsModel, TimeSeriesSet, TimeZone


class ExportRunEntry(FewsModel):
    folder: str
    timeSeriesSet: list[TimeSeriesSet] = Field(min_length=1)
    validate_: bool | None = Field(default=None, alias="validate")
    idMapId: str | None = None
    unitConversionsId: str | None = None
    flagConversionsId: str | None = None
    exportMissingValues: bool | None = None
    exportEmptyHeaders: bool | None = None
    exportFilePrefix: str | None = None
    exportTimeZone: TimeZone | None = None
    exportMissingValue: Decimal | None = None
    temporaryFilePrefix: str | None = None


class ExportRun(FewsModel):
    export: list[ExportRunEntry] = Field(min_length=1)
