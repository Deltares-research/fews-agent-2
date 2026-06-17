"""DataDownloadDisplay.xml — Web OC data-download menu templates."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel


class LocationAttributes(FewsModel):
    """`<locationAttributes>` wrapper around `<attributeId>` elements."""

    attributeId: list[str] = Field(min_length=1)


class DataDownloadTemplate(FewsModel):
    id: str | None = None
    showLocationName: Literal["id", "short name", "name"]
    showParameterName: Literal["id", "short name", "name"]
    locationAttributes: LocationAttributes


class DataDownloadDisplay(FewsModel):
    """Root of DataDownloadDisplay.xml."""

    displayTemplate: list[DataDownloadTemplate] = Field(min_length=1)
