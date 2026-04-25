"""WebOCComponentSettings.xml — component-behaviour overrides for Web OC.

Top level: ``<componentSettings id="...">`` groups of three optional
sub-sections — ``<map>``, ``<charts>``, ``<ssd>``.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import FewsModel


NumberOfLines = Literal["1", "2", "3", "All"]
LegendPlacement = Literal[
    "above chart", "under chart",
    "inside upper right", "inside lower right",
    "inside upper left", "inside lower left",
]
DefaultPanelPlacement = Literal["left", "right", "bottom", "up", "detached"]
PanelPlacement = Literal["left", "right", "bottom", "up", "all", "detached"]
StartPanel = Literal[
    "metaDataPanel", "timeSeriesChart", "timeSeriesTable",
    "verticalProfileChart", "verticalProfileTable",
]
Toolbar = Literal["false", "true", "auto"]
Sorting = Literal["ascending", "descending"]


class LocationsLayerZoomLevel(FewsModel):
    level: int
    levelLocationAttribute: str | None = None


class WebOCExternalLayer(FewsModel):
    id: str
    name: str
    styleJsonFile: str | None = None
    visible: bool | None = None


class OverLay(FewsModel):
    """Choice: overlayId (reference) XOR externalLayer (inline). ``visible``
    is allowed in either branch."""

    overlayId: str | None = None
    externalLayer: WebOCExternalLayer | None = None
    visible: bool | None = None

    @model_validator(mode="after")
    def _one_branch(self) -> OverLay:
        if (self.overlayId is None) == (self.externalLayer is None):
            raise ValueError(
                "overlay: supply exactly one of overlayId or externalLayer"
            )
        return self


class GridLayer(FewsModel):
    """Inlined from sharedTypes — just description + viewPermission."""

    description: str | None = None
    viewPermission: str | None = None


class Overlays(FewsModel):
    """XSD choice-unbounded over overlay / gridLayer — parallel-list pattern.

    Per XSD, ``gridLayer`` appears with ``minOccurs=0`` (no maxOccurs), so
    there's at most one. We keep it as a single optional field."""

    overlay: list[OverLay] = Field(default_factory=list)
    gridLayer: GridLayer | None = None


class WebOCWmsLayer(FewsModel):
    show: bool
    autoPlay: bool | None = None
    animateVectors: bool | None = None
    doubleClickAction: bool | None = None


class LocationsLayer(FewsModel):
    show: bool
    locationNames: bool | None = None
    singleClickAction: bool | None = None
    locationSearchEnabled: bool | None = None
    minZoom: LocationsLayerZoomLevel | None = None
    maxZoom: LocationsLayerZoomLevel | None = None


class WebOCMap(FewsModel):
    wmsLayer: WebOCWmsLayer | None = None
    locationsLayer: LocationsLayer | None = None
    overlays: Overlays | None = None


class GeneralChart(FewsModel):
    startPanel: StartPanel | None = None
    toolbar: Toolbar | None = None
    locationNames: bool | None = None


class PanelPlacementBlock(FewsModel):
    defaultPlacement: DefaultPanelPlacement
    allowedPlacement: list[PanelPlacement] = Field(default_factory=list)


class WebOCAction(FewsModel):
    panelPlacement: PanelPlacementBlock | None = None
    downloadData: bool | None = None
    downloadMetaData: bool | None = None
    downloadFigure: bool | None = None


class TimeSeriesChartLegend(FewsModel):
    enabled: bool
    minNumberOfLines: NumberOfLines | None = None
    maxNumberOfLines: NumberOfLines | None = None
    placement: LegendPlacement | None = None


class WebOcXAxis(FewsModel):
    enabled: bool
    xTicks: bool
    xLabel: bool


class WebOcYAxis(FewsModel):
    enabled: bool
    yTicks: bool
    yLabel: bool


class TimeSeriesChart(FewsModel):
    enabled: bool
    locationEnabledAttribute: str | None = None
    legend: TimeSeriesChartLegend | None = None
    xAxis: WebOcXAxis | None = None
    yAxis: WebOcYAxis | None = None


class TimeSeriesTable(FewsModel):
    enabled: bool
    locationEnabledAttribute: str | None = None
    allowDateTimeSorting: bool | None = None
    sortDateTimeColumn: Sorting | None = None


class VerticalProfileTable(FewsModel):
    enabled: bool
    locationEnabledAttribute: str | None = None
    allowDepthColumnSorting: bool | None = None
    sortDepthColumn: Sorting | None = None


class MetaDataPanel(FewsModel):
    enabled: bool
    locationEnabledAttribute: str | None = None


class WebOCChart(FewsModel):
    general: GeneralChart | None = None
    actions: WebOCAction | None = None
    timeSeriesChart: TimeSeriesChart | None = None
    timeSeriesTable: TimeSeriesTable | None = None
    verticalProfileChart: TimeSeriesChart | None = None
    verticalProfileTable: VerticalProfileTable | None = None
    metaDataPanel: MetaDataPanel | None = None


class WebOCSSD(FewsModel):
    zoomEnabled: bool | None = None
    useBrowserStyle: bool | None = None


class ComponentSettings(FewsModel):
    id: str
    map: WebOCMap | None = None
    charts: WebOCChart | None = None
    ssd: WebOCSSD | None = None


class WebOCComponentSettings(FewsModel):
    componentSettings: list[ComponentSettings] = Field(min_length=1)
