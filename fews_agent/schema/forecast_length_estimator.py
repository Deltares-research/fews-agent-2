"""ForecastLengthEstimator (SetForecastLengthTemplate).

Tiny config type: one input forecast time series defines the forecast
length, constrained by a minimum duration.
"""
from __future__ import annotations

from .common import FewsModel, TimeSeriesSet, UnitMultiplier


class ForecastLengthEstimator(FewsModel):
    """Root of SetForecastLength*.xml.

    `externalForecastTimeSeries` carries the standard TimeSeriesSet shape
    (moduleInstanceId, valueType, parameterId, ...); the XML wraps it in
    an `<externalForecastTimeSeries>` element rather than `<timeSeriesSet>`.
    """

    externalForecastTimeSeries: TimeSeriesSet
    minForecastLength: UnitMultiplier
