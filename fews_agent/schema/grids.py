"""Grids.xml — typed wrapper around the broad grids XSD."""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel


class Grids(FewsModel):
    """Root of Grids.xml. Body interleaves `<regular>` and `<irregular>`
    child elements; child-element order matters, so the body is held as
    a list of single-key dicts."""

    body: list[dict[str, Any]] | dict[str, Any] = Field(default_factory=list)
