"""CommonAdapter.xml — legacy generic adapter config.

Marked ``LEGACY, NO LONGER USED`` in the XSD. Keeps its own types for
the activities tree: each activity is either a ``profile`` (per-point
mapping) or a ``timeSeries`` (per-column mapping).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from .common import FewsModel, TimeStep, TimeZone


ColumnSeparator = Literal["space", "tab"]


class CommonAdapterGeneral(FewsModel):
    workDir: str
    importDir: str
    exportDir: str
    missingValue: Decimal
    stateDir: str | None = None
    diagnosticFile: str | None = None
    columnSeperator: ColumnSeparator | None = None
    timeZone: TimeZone | None = None


class CommonAdapterPointMapping(FewsModel):
    id: str
    column: int


class CommonAdapterMapping(FewsModel):
    parameterId: str
    locationId: str
    column: int


class CommonAdapterProfileActivity(FewsModel):
    parameterId: str
    locationId: str
    points: list[CommonAdapterPointMapping] = Field(min_length=1)


class CommonAdapterTimeSeriesActivity(FewsModel):
    mapping: list[CommonAdapterMapping] = Field(min_length=1)


class CommonAdapterActivity(FewsModel):
    """XSD choice: profile XOR timeSeries (exactly one)."""

    dateFormat: str
    input: list[str] = Field(min_length=1)
    output: list[str] = Field(min_length=1)
    profile: CommonAdapterProfileActivity | None = None
    timeSeries: CommonAdapterTimeSeriesActivity | None = None
    timeStep: TimeStep | None = None
    moduleLogFile: str | None = None
    stateFile: str | None = None

    @model_validator(mode="after")
    def _one_variant(self) -> CommonAdapterActivity:
        has_p = self.profile is not None
        has_ts = self.timeSeries is not None
        if has_p == has_ts:
            raise ValueError(
                "commonAdapter activity: supply exactly one of profile / timeSeries"
            )
        return self


class CommonAdapterActivities(FewsModel):
    preAdapterActivities: list[CommonAdapterActivity] = Field(default_factory=list)
    postAdapterActivities: list[CommonAdapterActivity] = Field(default_factory=list)


class CommonAdapter(FewsModel):
    general: CommonAdapterGeneral
    activities: CommonAdapterActivities
