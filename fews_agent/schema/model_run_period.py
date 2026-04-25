"""ModelRunPeriod.xml — absolute period (startDate + endDate) for a model run."""
from __future__ import annotations

from .common import FewsModel


class ModelRunPeriodWindow(FewsModel):
    """`<period>` child — XSD PeriodComplexType."""

    startDate: str
    endDate: str


class ModelRunPeriod(FewsModel):
    """Root of ModelRunPeriod.xml."""

    period: ModelRunPeriodWindow
    # XSD fixes version at 1.1 for this file.
    version: str = "1.1"
