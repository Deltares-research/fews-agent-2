"""DynamicReportDisplays.xml — near-identical structural twin of
HtmlTemplateDisplays.xml (XSDs differ only in root element + type-name
prefixes). We reuse every inner type from html_template_displays and
just wrap them in DynamicReport-prefixed classes where the XSD
demands element uniqueness via a distinct complexType name.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel, TimeSeriesSet
from .html_template_displays import (
    DataObject,
    TimeSeriesSetReferences,
)


class DynamicReportDisplay(FewsModel):
    id: str
    name: str | None = None
    dataObject: list[DataObject] = Field(min_length=1)
    reportTemplateName: str | None = None


class DynamicReportDisplays(FewsModel):
    """Root of DynamicReportDisplays.xml."""

    timeSeriesSet: list[TimeSeriesSet] = Field(min_length=1)
    timeSeriesSets: list[TimeSeriesSetReferences] = Field(default_factory=list)
    display: list[DynamicReportDisplay] = Field(min_length=1)
