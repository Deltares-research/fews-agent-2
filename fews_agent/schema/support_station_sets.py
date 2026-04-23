"""SupportStationSets.xml — declares support-station relationships for
the Support Location Module (infilling from neighbour stations)."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel, TimeSeriesSet


class SupportStationSet(FewsModel):
    supportStationTimeSeriesSet: TimeSeriesSet
    # Note: the XSD uses `<TimeSeriesSet>` (capital T) inside dataTimeSeriesSets.
    # We use the snake_case alias `dataTimeSeriesSet` for the input dict key
    # since the XSD exception is a one-off oddity, but the template emits the
    # capitalised tag to match the XSD.
    dataTimeSeriesSet: list[TimeSeriesSet] = Field(min_length=1)


class SupportStationSets(FewsModel):
    """Root of SupportStationSets.xml."""

    supportStationSet: list[SupportStationSet] = Field(min_length=1)
