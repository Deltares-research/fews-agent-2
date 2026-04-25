"""FlagSourceColumns.xml — extra flag columns shown alongside time series."""
from __future__ import annotations

from typing import Annotated

from pydantic import Field

from .common import FewsModel


class FlagSourceColumn(FewsModel):
    id: str
    name: str | None = None
    # storageKey must stay stable forever — see XSD annotation. Range 0-127.
    storageKey: Annotated[int, Field(ge=0, le=127)]
    description: str | None = None
    shortName: str | None = None
    toolTip: str | None = None
    editable: bool | None = None
    alwaysVisible: bool | None = None
    clearOnValueOrFlagChange: bool | None = None
    backgroundColor: str | None = None


class TimeOfValidity(FewsModel):
    columnId: str
    defaultFlagSource: str


class FlagSourceColumns(FewsModel):
    """Root of FlagSourceColumns.xml. Both children optional per XSD."""

    column: list[FlagSourceColumn] = Field(default_factory=list)
    timeOfValidity: TimeOfValidity | None = None
