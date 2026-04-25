"""ForecastMixer.xml — mixes input timeseries into output timeseries.

One ``<mixing>`` entry per calculation: input filters + output filter +
weighting method. Reuses the shared TimeSeriesFilter model (common.py).
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel, TimeSeriesFilter


ForecastMixerWeights = Literal["userDefinedWeights", "equalWeights"]


class ForecastMixing(FewsModel):
    id: str
    inputTimeSeries: list[TimeSeriesFilter] = Field(min_length=1)
    outputTimeSeries: TimeSeriesFilter
    weightingMethod: ForecastMixerWeights


class ForecastMixer(FewsModel):
    mixing: list[ForecastMixing] = Field(min_length=1)
