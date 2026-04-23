"""OpenDACalibrationDisplay.xml — kicks off an OpenDA calibration run."""
from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from .common import FewsModel, TimeSeriesSet


class CalibrationParameter(FewsModel):
    label: str
    initialValue: Decimal
    stdDev: Decimal
    lowerBound: Decimal | None = None
    upperBound: Decimal | None = None


class OpenDACalibrationDisplay(FewsModel):
    """Root of OpenDACalibrationDisplay.xml."""

    fileExchangeDirectory: str
    modelParametersFileName: str
    modelResultsFileName: str
    workflowId: str
    openDABinDir: str
    calibrationParameter: list[CalibrationParameter] = Field(min_length=1)
    observedTimeSeriesSet: TimeSeriesSet
    resultsTimeSeriesSet: TimeSeriesSet
