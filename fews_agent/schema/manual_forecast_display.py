"""ManualForecastDisplay.xml — forecaster UI for manual/predefined runs."""
from __future__ import annotations

from .common import FewsModel


class RunningPredefined(FewsModel):
    description: str | None = None
    directory: str | None = None
    buttonVisible: bool | None = None


class ManualForecastDisplay(FewsModel):
    """Root of ManualForecastDisplay.xml."""

    runningPredefined: RunningPredefined | None = None
