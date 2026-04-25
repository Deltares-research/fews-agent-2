"""DisplayGroups.xml — typed wrapper around the displayGroups XSD."""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel


class DisplayGroups(FewsModel):
    """Root of DisplayGroups.xml. Body holds plot/displayGroup children
    via dict_to_xml passthrough."""

    body: list[dict[str, Any]] | dict[str, Any] = Field(default_factory=list)
