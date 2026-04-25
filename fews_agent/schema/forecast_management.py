"""ForecastManagement.xml — Forecast Management tab configuration."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel
from .modifier_types import TimeSpan
from .trend_display import RelativeTime


class TimeThreshold(FewsModel):
    """XSD TimeThresholdComplexType — period + colour + optional event-code pair.

    eventCode and logLevel must be supplied together (they're a sub-sequence
    with minOccurs=0 in the XSD). We don't enforce pairing at the model
    level since it's not expressible via Pydantic without a validator;
    the XSD will catch mismatches.

    ``graceTime`` (since 2025.02) deduplicates repeated log messages for
    a missing data feed within the configured span.
    """

    periodLength: RelativeTime
    color: str
    eventCode: str | None = None
    logLevel: str | None = None
    graceTime: TimeSpan | None = None


class DefaultTimeThreshold(FewsModel):
    timeThreshold: list[TimeThreshold] = Field(min_length=1)


class ExtraDispatchTimeThreshold(FewsModel):
    workflowId: list[str] = Field(default_factory=list)
    workflowIdPattern: list[str] = Field(default_factory=list)
    timeThreshold: list[TimeThreshold] = Field(min_length=1)


class ForecastManagement(FewsModel):
    """Root of ForecastManagement.xml."""

    defaultDispatchTimeThreshold: DefaultTimeThreshold
    extraDispatchTimeThreshold: list[ExtraDispatchTimeThreshold] = Field(
        default_factory=list
    )
