"""HymosTransferDbImportRun.xml — import from HyMOS transfer databases."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel, TimeSeriesSet, TimeZone


class HymosTransferDbImportTask(FewsModel):
    importDirectory: str
    idMapId: str | None = None
    unitConversionsId: str | None = None
    flagConversionsId: str | None = None
    timeSeriesSet: list[TimeSeriesSet] = Field(min_length=1)
    importTimeZone: TimeZone | None = None


class HymosTransferDbImportRun(FewsModel):
    """Root of HymosTransferDbImportRun.xml."""

    # XSD element name is <import>, which is a Python keyword.
    import_: list[HymosTransferDbImportTask] = Field(
        min_length=1, alias="import"
    )
