"""CustomColors.xml — catalog of named color keys that other configs
can reference by key (palette abstraction)."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class CustomColorKey(FewsModel):
    key: str
    color: str | None = None


class CustomColors(FewsModel):
    """Root of CustomColors.xml."""

    defaultCustomColorKeys: list[CustomColorKey] = Field(min_length=1)
    # Optional attribute with fixed="1.0"; leave optional to emit only when set.
    version: str | None = None
