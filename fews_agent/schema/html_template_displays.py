"""HtmlTemplateDisplays.xml — HTML report templating (fills variables
from time-series sets).

Inner types live here but the same structural types are reused verbatim
in ``dynamic_report_displays`` (same XSD shape, different root element
and type-name prefix).
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import FewsModel, RelativeViewPeriod, TimeSeriesSet, TimeStep


class TimeSeriesSetReferences(FewsModel):
    id: str
    name: str | None = None
    timeSeriesSetId: list[str] = Field(min_length=1)


class TimeSeriesSetVariable(FewsModel):
    id: str
    timeSeriesSetId: str


class LoopTimeSeriesSetVariable(FewsModel):
    id: str
    timeSeriesSetsId: str


class LoopLocationVariable(FewsModel):
    id: str
    locationSetId: str | None = None


class SelectedLocationVariable(FewsModel):
    id: str
    validLocationSetId: str


class SelectedTimeVariable(FewsModel):
    id: str
    timeStep: TimeStep
    relativeViewPeriod: RelativeViewPeriod


class LoopEnsembleMemberVariable(FewsModel):
    name: str
    timeSeriesSetId: str | None = None


class HtmlTemplateRequiredValue(FewsModel):
    function: str


class HtmlTemplateField(FewsModel):
    id: str
    function: str
    name: str | None = None
    sort: Literal["ascending", "descending"] | None = None
    required: bool | None = None


class DataObject(FewsModel):
    id: str
    field: list[HtmlTemplateField] = Field(min_length=1)
    timeSeriesSetVariable: list[TimeSeriesSetVariable] = Field(default_factory=list)
    loopTimeSeriesSetVariable: LoopTimeSeriesSetVariable | None = None
    loopLocationVariable: LoopLocationVariable | None = None
    selectedLocationVariable: SelectedLocationVariable | None = None
    selectedTimeVariable: SelectedTimeVariable | None = None
    loopEnsembleMemberVariable: LoopEnsembleMemberVariable | None = None
    requiredValue: list[HtmlTemplateRequiredValue] = Field(default_factory=list)

    @model_validator(mode="after")
    def _loop_xor_selected_location(self) -> DataObject:
        has_loop = self.loopLocationVariable is not None
        has_sel = self.selectedLocationVariable is not None
        if has_loop and has_sel:
            raise ValueError(
                "dataObject: loopLocationVariable and selectedLocationVariable "
                "are mutually exclusive"
            )
        return self


class HtmlTemplateDisplay(FewsModel):
    id: str
    name: str | None = None
    dataObject: list[DataObject] = Field(min_length=1)
    reportTemplateName: str | None = None


class HtmlTemplateDisplays(FewsModel):
    """Root of HtmlTemplateDisplays.xml."""

    timeSeriesSet: list[TimeSeriesSet] = Field(min_length=1)
    timeSeriesSets: list[TimeSeriesSetReferences] = Field(default_factory=list)
    display: list[HtmlTemplateDisplay] = Field(min_length=1)
