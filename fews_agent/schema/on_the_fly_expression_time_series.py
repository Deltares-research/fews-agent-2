"""OnTheFlyExpressionTimeSeries.xml — declares a parameter-group formula
that's evaluated on the fly from the contributing time series."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel, TimeSeriesSet


class OnTheFlyExpressionTimeSeriesDefinition(FewsModel):
    name: str
    parameterGroupId: str
    formula: str
    timeSeriesSet: list[TimeSeriesSet] = Field(min_length=1)


class OnTheFlyExpressionTimeSeries(FewsModel):
    """Root of OnTheFlyExpressionTimeSeries.xml."""

    onTheFlyExpressionTimeSeriesDefinition: OnTheFlyExpressionTimeSeriesDefinition
