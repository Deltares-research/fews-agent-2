"""StateEditor.xml — per-model state editor configuration.

The optional ``<timeSeriesDisplay>`` sub-section reuses the full
``TimeSeriesDisplay`` model (same XSD complexType). Both rendering
sites share ``_partials/time_series_display_body.xml.j2``.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator


from .common import FewsModel
from .time_series_display_config import TimeSeriesDisplay


SeriesQualifier = Literal["min", "max", "mean"]


class StateEditorGeneral(FewsModel):
    displayName: str
    timeZone: float | None = None  # TimeZoneSimpleType (decimal hours)


class ModelGroup(FewsModel):
    """Choice: modelId[] XOR modelGroupId[]."""

    id: str
    name: str | None = None
    description: str | None = None
    modelId: list[str] = Field(default_factory=list)
    modelGroupId: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_branch(self) -> ModelGroup:
        if bool(self.modelId) == bool(self.modelGroupId):
            raise ValueError(
                "modelGroup: supply exactly one of modelId[] or modelGroupId[]"
            )
        return self


class ModelGroups(FewsModel):
    modelGroup: list[ModelGroup] = Field(min_length=1)


class Model(FewsModel):
    id: str
    name: str | None = None
    stateParameterGroupId: list[str] = Field(min_length=1)
    locationId: str | None = None
    resultSeriesGroupId: list[str] = Field(default_factory=list)


class StateRange(FewsModel):
    min: float
    max: float


class StateSeries(FewsModel):
    """Attribute-only element — ``id``, ``locationId`` (keyword ALL allowed),
    ``parameterId``, optional ``qualifier`` (min/max/mean)."""

    id: str
    locationId: str
    parameterId: str
    qualifier: SeriesQualifier | None = None


class Event(FewsModel):
    """Attribute-only element: date/time + mean/min/max values."""

    date: str
    time: str
    mean: float | None = None
    min: float | None = None
    max: float | None = None


class Climatology(FewsModel):
    event: list[Event] = Field(default_factory=list)


class StateParameter(FewsModel):
    """Choice for climatology: ``climatology`` (event list) XOR
    ``climatologySeries`` (up to 3 StateSeries with min/max/mean
    qualifiers)."""

    id: str
    name: str | None = None
    range: StateRange
    inputSeries: StateSeries
    outputSeries: StateSeries
    climatology: Climatology | None = None
    climatologySeries: list[StateSeries] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def _one_climatology(self) -> StateParameter:
        if self.climatology is not None and self.climatologySeries:
            raise ValueError(
                "stateParameter: climatology and climatologySeries are mutually "
                "exclusive"
            )
        return self


class SeriesGroup(FewsModel):
    id: str
    series: list[StateSeries] = Field(min_length=1)


class StateParameterGroup(FewsModel):
    id: str
    stateParameterId: list[str] = Field(min_length=1)


class StateEditor(FewsModel):
    general: StateEditorGeneral
    modelGroups: ModelGroups
    model: list[Model] = Field(min_length=1)
    stateParameterGroup: list[StateParameterGroup] = Field(min_length=1)
    stateParameter: list[StateParameter] = Field(min_length=1)
    seriesGroup: list[SeriesGroup] = Field(default_factory=list)
    timeSeriesDisplay: TimeSeriesDisplay | None = None
