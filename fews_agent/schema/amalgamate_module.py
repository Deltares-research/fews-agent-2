"""AmalgamateModule.xml — inactive time-series amalgamation config.

Marked ``INACTIVE`` in the XSD. Each ``<task>`` declares a
``maximumCombinedBlobLength`` duration plus the input timeSeriesSets
to be amalgamated.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel, TimeSeriesSet, UnitMultiplier


class AmalgamateTask(FewsModel):
    maximumCombinedBlobLength: UnitMultiplier
    timeSeriesSet: list[TimeSeriesSet] = Field(min_length=1)


class AmalgamateModule(FewsModel):
    task: list[AmalgamateTask] = Field(min_length=1)
