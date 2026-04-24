"""ManualForecastDisplay.xml — forecaster UI for manual/predefined runs."""
from __future__ import annotations

from .common import FewsModel, RelativePeriod, UnitMultiplier


class RunningPredefined(FewsModel):
    description: str | None = None
    directory: str | None = None
    buttonVisible: bool | None = None


class ManualForecastColdState(FewsModel):
    """Cold-state startDate is a TimeSpan (unit+multiplier relative to
    forecast time)."""

    startDate: UnitMultiplier


class ManualForecastWarmState(FewsModel):
    stateSearchPeriod: RelativePeriod


class ManualForecastTask(FewsModel):
    """Task definition exposed in the Manual Forecast dialog. Attributes
    drive which UI selections are available; child blocks populate the
    defaults for each."""

    workflowId: str | None = None
    stateSelection: str | None = None  # state selection UI hint
    forecastLengthSelection: str | None = None
    coldState: ManualForecastColdState | None = None
    warmState: ManualForecastWarmState | None = None
    forecastLength: UnitMultiplier | None = None


class ManualForecastDisplay(FewsModel):
    """Root of ManualForecastDisplay.xml.

    XSD sequence order: runningPredefined, coldState, warmState,
    forecastLength, task. All optional.
    """

    runningPredefined: RunningPredefined | None = None
    coldState: ManualForecastColdState | None = None
    warmState: ManualForecastWarmState | None = None
    forecastLength: UnitMultiplier | None = None
    task: ManualForecastTask | None = None
