"""Filters.xml — typed wrapper around the recursive filters XSD."""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel


class Filters(FewsModel):
    """Root of Filters.xml."""

    body: list[dict[str, Any]] | dict[str, Any] = Field(default_factory=list)
