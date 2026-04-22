"""Generic FEWS XML file with a single dict body.

Used for config file types whose structure is too broad or too UI-specific
to merit field-by-field Pydantic modeling: Products, Grids, LocationSets,
Filters, DisplayGroups, Explorer, SpatialDisplay. Every such file is
represented as a dict of top-level children, emitted via the `dict_to_xml`
Jinja filter using the `@attr` convention.

Future work: promote commonly-used sub-shapes (csvFile, plot, line,
extentBox, ...) into proper typed models as they become load-bearing.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel


class GenericXmlFile(FewsModel):
    """One root element's children, stored as a dict OR a list of single-key
    dicts. Use the list form when child-element order matters (e.g. Grids
    interleaves <regular> and <irregular>)."""

    body: list[dict[str, Any]] | dict[str, Any] = Field(default_factory=list)
