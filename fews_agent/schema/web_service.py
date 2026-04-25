"""WebService.xml — legacy embedded web-service config.

Marked ``LEGACY, NO LONGER USED`` in the XSD. Configures an in-OC/SA
web service: port, timeout, and the Pi time-series file paths it
exchanges with the running workflow.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class MCTaskWebService(FewsModel):
    hostname: str
    port: int


class WebService(FewsModel):
    port: int
    timeOutSeconds: int
    inputPiTimeSeriesFile: str
    outputPiTimeSeriesFile: list[str] = Field(min_length=1)
    mcTaskWebService: MCTaskWebService | None = None
