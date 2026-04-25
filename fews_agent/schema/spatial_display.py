"""SpatialDisplay.xml — typed wrapper around the spatialDisplay XSD."""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel


class SpatialDisplay(FewsModel):
    """Root of SpatialDisplay.xml. Body holds gridPlotGroup/gridPlot/...
    children via dict_to_xml passthrough."""

    body: list[dict[str, Any]] | dict[str, Any] = Field(default_factory=list)
