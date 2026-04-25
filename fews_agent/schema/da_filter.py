"""DAFilter.xml — DA-executive module-instance adapter config.

XSD root element is ``<dAFilter>`` (note capitalisation) with fixed
``version="1.1"``.
"""
from __future__ import annotations

from .common import FewsModel


class DAFilter(FewsModel):
    """Root of DAFilter.xml."""

    description: str | None = None
    daExecutiveRootDir: str | None = None
    referencePiTimeSeries: str
    daExecutiveModelRunPeriodFile: str
    diagnosticFile: str | None = None
    # XSD fixes version at 1.1.
    version: str = "1.1"
