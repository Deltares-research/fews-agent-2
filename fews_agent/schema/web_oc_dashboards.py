"""WebOCDashboards.xml — Web OC dashboard layouts.

Each dashboard references a CSS grid template and contains groups of
elements; each element places items (topologyNode + component) into a
grid area.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel


WebOCDashboardComponent = Literal[
    "map",
    "schematic-status-display",
    "charts",
    "report",
    "system-monitor",
    "dynamic-report-display",
    "log-display",
    "data-download-display",
    "runtask-display",
]


class WebOCDashboardItem(FewsModel):
    topologyNodeId: str
    component: WebOCDashboardComponent
    componentSettingsId: str | None = None
    actionId: list[str] = Field(default_factory=list)


class WebOCDashboardItems(FewsModel):
    item: list[WebOCDashboardItem] = Field(min_length=1)


class WebOCDashboardElement(FewsModel):
    gridTemplateArea: str
    items: WebOCDashboardItems


class WebOCDashboardElements(FewsModel):
    element: list[WebOCDashboardElement] = Field(min_length=1)


class WebOCDashboardGroup(FewsModel):
    elements: WebOCDashboardElements


class WebOCDashboardGroups(FewsModel):
    group: list[WebOCDashboardGroup] = Field(min_length=1)


class WebOCDashboard(FewsModel):
    id: str
    name: str | None = None
    cssTemplate: str
    groups: WebOCDashboardGroups
    viewPermission: str | None = None


class WebOCDashboards(FewsModel):
    dashboard: list[WebOCDashboard] = Field(min_length=1)
