"""TimeSeriesButtonsPanels.xml — topology-referenced button panels.

Each panel carries radio-button groups; each button wraps a
``TimeSeriesFilter`` used to select which time series from the plot /
workflow the button applies to.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel, TimeSeriesFilter


class TsButtonsButton(FewsModel):
    """Extends TimeSeriesFilter with button layout metadata.

    The XSD embeds a ``TimeSeriesFilterGroup`` inside ButtonComplexType,
    so all filter fields live alongside groupId/row/column attributes
    and the optional tooltip / default-pattern child elements.
    """

    groupId: str
    row: int = Field(ge=1)
    column: int = Field(ge=1)
    name: str | None = None
    defaultForTopologyNodeIdPattern: str | None = None
    toolTip: str | None = None
    filter: TimeSeriesFilter = Field(default_factory=TimeSeriesFilter)


class TsButtonsPanel(FewsModel):
    id: str
    resolveInWorkflow: bool
    resolveInPlots: bool
    button: list[TsButtonsButton] = Field(min_length=1)


class TimeSeriesButtonsPanels(FewsModel):
    panel: list[TsButtonsPanel] = Field(min_length=1)
