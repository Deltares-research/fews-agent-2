"""Explorer.xml — typed wrapper around the explorer XSD."""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel


class Explorer(FewsModel):
    """Root of Explorer.xml. Body holds explorerTask/explorerView/...
    children via dict_to_xml passthrough."""

    body: list[dict[str, Any]] | dict[str, Any] = Field(default_factory=list)
