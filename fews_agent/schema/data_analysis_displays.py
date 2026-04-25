"""DataAnalysisDisplays.xml — Web OC data-analysis display definitions."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel, RelativeViewPeriod


class DataAnalysisFilter(FewsModel):
    """`<filters><filterId>...</filterId>+</filters>`."""

    filterId: list[str] = Field(min_length=1)


class LocationSelection(FewsModel):
    name: str | None = None


class ParameterSelection(FewsModel):
    name: str | None = None


class ModuleInstanceSelection(FewsModel):
    name: str | None = None


class LocationAttributeSelection(FewsModel):
    attributeId: str
    name: str


class SelectionPanel(FewsModel):
    locationSelection: LocationSelection
    parameterSelection: ParameterSelection
    moduleInstanceSelection: ModuleInstanceSelection | None = None
    locationAttributeSelection: list[LocationAttributeSelection] = Field(
        default_factory=list
    )


class DataAnalysisDisplayResults(FewsModel):
    filterId: str | None = None
    archiveProductId: list[str] = Field(default_factory=list)


class DataAnalysisDisplayWorkflow(FewsModel):
    id: str
    name: str | None = None
    workflowId: str
    results: DataAnalysisDisplayResults
    iconId: str | None = None


class ToolBoxes(FewsModel):
    """Matches XSD ToolBoxesComplexType.

    ``resampling`` / ``correlation`` are ``emptyElement`` flags in the XSD —
    when the user sets the bool true the template emits ``<resampling/>``.
    """

    resampling: bool = False
    correlation: bool = False
    workflow: list[DataAnalysisDisplayWorkflow] = Field(default_factory=list)


class ExportArchiveProductAttribute(FewsModel):
    key: str
    value: str


class ExportArchiveProductsAttributes(FewsModel):
    attribute: list[ExportArchiveProductAttribute] = Field(min_length=1)


class ExportArchiveProductProperties(FewsModel):
    areaId: str
    sourceId: str | None = None


class ExportArchiveProductMetaData(FewsModel):
    properties: ExportArchiveProductProperties
    attributes: ExportArchiveProductsAttributes | None = None


class ExportArchiveProduct(FewsModel):
    enabled: bool
    metaData: ExportArchiveProductMetaData


class DataAnalysisDisplay(FewsModel):
    id: str
    name: str | None = None
    relativeViewPeriod: RelativeViewPeriod
    filters: DataAnalysisFilter
    selectionPanel: SelectionPanel | None = None
    toolBoxes: ToolBoxes
    exportArchiveProducts: ExportArchiveProduct | None = None


class DataAnalysisDisplays(FewsModel):
    dataAnalysisDisplay: list[DataAnalysisDisplay] = Field(min_length=1)
