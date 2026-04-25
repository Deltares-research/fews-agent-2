"""GridPlotGroups.xml — display config grouping grid plots.

The XSD root is tiny: a list of ``gridPlotGroup`` elements, each carrying a
required id and a recursive structure of nested groups + GridPlotComplexType
plots. ``GridPlotComplexType`` is large (40+ branches, layers, classBreaks,
animations) and dominated by display details — represented here as a
``dict[str, Any]`` passthrough rather than enumerating every optional.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel


class GridPlotGroup(FewsModel):
    """One ``<gridPlotGroup>`` — recursive container of plots / sub-groups.

    XSD GridPlotGroupComplexType:
      sequence:
        - description (str, optional)
        - viewPermission (str, optional)
        - highlight (bool, optional, default false)
        - choice (1..n) of:
            gridPlot           (GridPlotComplexType)
            singleLocationGridPlots (GridPlotComplexType)
            gridPlotGroup      (recursive)
      attributes: id (required), name (optional)

    The choice's child-order matters in XML. We surface plots/groups via
    a single ordered ``children`` list of single-key dicts rather than
    three parallel lists, mirroring the approach used elsewhere for
    ordered XSD choices.
    """

    id: str
    name: str | None = None
    description: str | None = None
    viewPermission: str | None = None
    highlight: bool | None = None
    # Ordered list of single-key dicts:
    #   {"gridPlot": {...}}
    #   {"singleLocationGridPlots": {...}}
    #   {"gridPlotGroup": {...}}
    # Each value is a passthrough dict rendered via dict_to_xml.
    children: list[dict[str, Any]] = Field(default_factory=list)


class GridPlotGroups(FewsModel):
    """Root of GridPlotGroups.xml."""

    gridPlotGroup: list[GridPlotGroup] = Field(min_length=1)
