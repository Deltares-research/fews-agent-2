"""ChartLayer.xml — chart layer for the FEWS Explorer map.

XSD root: ``chartLayer`` (ChartLayerComplexType, version="1.0").

Top-level structure: optional refresh-interval, scale-range
(min/maxScale), repeating chartFormat templates, originalMapSize, and
one or more ``chart`` entries that bind a ChartFormat to a location.

The chart subtree (ChartLayerChartComplexType extends ChartComplexType)
is deeply nested (axis configs, areas, time-series styles, datum-axis,
threshold groups, ...). Per CLAUDE.md "use ``dict[str, Any]`` for
subtrees deeper than 3 nesting levels", we model the chart and
chartFormat bodies as ``dict[str, Any]`` passthroughs and only commit
to the few attributes/elements the caller is most likely to set on
each chart leaf.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel


class ChartLayerRefreshInterval(FewsModel):
    """TimeSpanComplexType — attribute-only. Obsolete since 2011.01 but
    still allowed by the XSD."""

    unit: str
    multiplier: int | None = None
    divider: int | None = None


class PixelDimension(FewsModel):
    """XSD PixelDimension — width/height in pixels (both optional)."""

    width: int | None = None
    height: int | None = None


class ChartLayer(FewsModel):
    """Root of ChartLayer.xml.

    The XSD's ChartLayerChartComplexType extends ChartComplexType — a
    deep subtree with leftAxis, rightAxis, datumAxis, areas, timeSeries,
    forecastConfidenceTimeSpans, etc. We accept each ``chart`` and each
    ``chartFormat`` as a ``dict[str, Any]`` body. The dict's ``@id``,
    ``@formatId``, ``@width``, ``@height`` keys carry the attributes;
    children keys carry elements in XSD-sequence order (caller
    responsibility — XSD validation enforces the rest).
    """

    version: str = "1.0"
    refreshInterval: ChartLayerRefreshInterval | None = None
    minScale: str | None = None
    maxScale: str | None = None
    chartFormat: list[dict[str, Any]] = Field(default_factory=list)
    originalMapSize: PixelDimension | None = None
    chart: list[dict[str, Any]] = Field(min_length=1)
