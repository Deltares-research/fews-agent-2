"""SupportStationSets.xml — declares support-station relationships for
the Support Location Module (infilling from neighbour stations)."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel, TimeSeriesSet
from .common import TimeSeriesSet as _TimeSeriesSet


class DataTimeSeriesSets(FewsModel):
    """`<dataTimeSeriesSets>` wrapper. XSD oddity: its child element is the
    capitalised `<TimeSeriesSet>` (not the usual lowercase `timeSeriesSet`),
    so the field is named to match the tag exactly and round-trips 1:1.
    The item type is referenced via the ``_TimeSeriesSet`` alias because the
    field name equals the class name (which would otherwise shadow it)."""

    TimeSeriesSet: list[_TimeSeriesSet] = Field(min_length=1)


class SupportStationSet(FewsModel):
    supportStationTimeSeriesSet: TimeSeriesSet
    dataTimeSeriesSets: DataTimeSeriesSets


class SupportStationSets(FewsModel):
    """Root of SupportStationSets.xml."""

    supportStationSet: list[SupportStationSet] = Field(min_length=1)
