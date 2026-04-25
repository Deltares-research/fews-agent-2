"""CalibrationSet.xml — legacy calibration configuration.

Single `<calibrationSet>` binds a workflow + module instance to an
observed / simulated series pair for a time-bounded period, plus an
optional stop-criteria block.
"""
from __future__ import annotations

from typing import Literal

from .common import FewsModel, Period, TimeSeriesSet


CalibrationMethod = Literal["superdud"]

ModulePerformance = Literal[
    "bias",
    "meanabsoluteerror",
    "meansquareerror",
    "nashsutcliffeefficiency",
    "peakmeansquareerror",
    "volumeerror",
    "MAE",
    "MSE",
    "NSE",
    "PeakMSE",
    "PercVol",
    "RMSE",
    "RMSF",
    "CorrelationCoeffient",
]


class CalibrationStopCriteria(FewsModel):
    """All three attributes optional per XSD (each with its own default)."""

    maxIterations: int | None = None
    minChangeinPerformance: float | None = None
    minChangeinParameterVector: float | None = None


class CalibrationSet(FewsModel):
    version: str = "1.1"
    id: str | None = None
    name: str
    calibrationMethod: CalibrationMethod
    description: str | None = None
    workflowDescriptorId: str
    moduleInstanceDescriptorId: str
    moduleParameterFileVersion: str
    calibrationPeriod: Period
    observedTimeSeriesSet: TimeSeriesSet
    simulatedTimeSeriesSet: TimeSeriesSet
    performanceIndicator: ModulePerformance
    stopCriteria: CalibrationStopCriteria | None = None
