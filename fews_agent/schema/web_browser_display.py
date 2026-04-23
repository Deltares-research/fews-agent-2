"""WebBrowserDisplay.xml — embedded Chromium browser in the FEWS UI."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class DomainAccess(FewsModel):
    origin: str | None = None


class DomainWhiteList(FewsModel):
    access: list[DomainAccess] = Field(min_length=1)


class WebBrowserDisplay(FewsModel):
    """Root of WebBrowserDisplay.xml."""

    defaultBrowser: bool | None = None
    bringToFront: bool | None = None
    lazyLoading: bool | None = None
    disablePrinting: bool | None = None
    chromiumSwitch: list[str] = Field(default_factory=list)
    domainWhiteList: DomainWhiteList
    downloadDir: str | None = None
    jcefBinDir: str | None = None
