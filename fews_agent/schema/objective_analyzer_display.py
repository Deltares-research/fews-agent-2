"""ObjectiveAnalyzerDisplay.xml — Kflows target-flow analysis display.

Each site tracks an observed discharge variable, optional peak variable,
and a pair of running-means variables. Target, lower- and upper-limit
``targetVariable``s are emitted as a group before the list of input
``<variable>`` definitions.
"""
from __future__ import annotations

from pydantic import Field

from .common import DataVariable, FewsModel, RelativeTime


class ObjectiveAnalyzerDisplayGeneral(FewsModel):
    description: str | None = None
    displayName: str
    periodBegin: int = Field(ge=0, le=24)
    periodLength: RelativeTime
    observedMeansParameterId: str


class ObservedVariable(FewsModel):
    variableId: str


class PeakVariable(FewsModel):
    variableId: str
    influencePeriodBefore: RelativeTime | None = None
    influencePeriodAfter: RelativeTime | None = None


class RunningMeans(FewsModel):
    allDataVariableId: str
    exTidalVariableId: str


class Site(FewsModel):
    name: str
    observedVariable: ObservedVariable
    peakVariable: PeakVariable | None = None
    runningMeans: RunningMeans


class MeansTable(FewsModel):
    variableId: str


class TargetVariable(FewsModel):
    """Paired with ``defaultValue`` (positiveDouble, passed through as str
    to preserve source digits like the Decimal convention elsewhere)."""

    variableId: str
    defaultValue: str


class ObjectiveAnalyzerDisplay(FewsModel):
    description: str | None = None
    general: ObjectiveAnalyzerDisplayGeneral
    site: list[Site] = Field(min_length=1)
    meansTable: MeansTable
    targetVariable: TargetVariable
    lowerTargetLimitVariable: TargetVariable
    upperTargetLimitVariable: TargetVariable
    variable: list[DataVariable] = Field(min_length=1)
