"""DataDownloadDisplay.xml — Web OC data-download menu templates."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel


class DataDownloadTemplate(FewsModel):
    id: str | None = None
    showLocationName: Literal["id", "short name", "name"]
    showParameterName: Literal["id", "short name", "name"]
    locationAttributes: list[str] = Field(min_length=1)


class DataDownloadDisplay(FewsModel):
    """Root of DataDownloadDisplay.xml."""

    displayTemplate: list[DataDownloadTemplate] = Field(min_length=1)
