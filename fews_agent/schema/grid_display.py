"""GridDisplay.xml — top-level grid plot display configuration.

XSD GridDisplayComplexType has 4 typed slots followed by a 1..n choice
of ``gridPlotGroup`` / ``gridPlotGroupId``. Both ``GridDisplayDefaults``
and inline ``GridPlotGroup`` are large recursive structures (geoMap,
classBreaks, contour values, plot trees), so deep sub-trees pass through
as ``dict[str, Any]`` to the dict_to_xml renderer.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from .common import FewsModel


class GridDisplay(FewsModel):
    """Root of GridDisplay.xml.

    XSD GridDisplayComplexType — sequence:
      - title (required)
      - showPlotTreeHideAllToolWindows (optional bool)
      - exportShapeIdFunction (optional)
      - defaults[] (optional)
      - choice (1..n) of gridPlotGroup / gridPlotGroupId
    """

    title: str
    showPlotTreeHideAllToolWindows: bool | None = None
    exportShapeIdFunction: str | None = None
    defaults: list[dict[str, Any]] = Field(default_factory=list)
    # Terminal choice exposed as two parallel optional lists; either or
    # both may be populated.
    gridPlotGroup: list[dict[str, Any]] = Field(default_factory=list)
    gridPlotGroupId: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _at_least_one_group(self) -> GridDisplay:
        if not self.gridPlotGroup and not self.gridPlotGroupId:
            raise ValueError(
                "gridDisplay: must contain at least one gridPlotGroup or "
                "gridPlotGroupId (XSD choice maxOccurs=unbounded, minOccurs=1)"
            )
        return self
