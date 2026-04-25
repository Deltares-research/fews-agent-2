"""CustomFlagSources.xml — predefined flag sources (100-255) beyond the
FEWS built-in set."""
from __future__ import annotations

from typing import Annotated

from pydantic import Field

from .common import FewsModel


class CustomFlagSource(FewsModel):
    id: str
    flag: Annotated[int, Field(ge=100, le=255)]
    name: str | None = None
    description: str | None = None


class CustomFlagSources(FewsModel):
    """Root of CustomFlagSources.xml. XSD: 1+ customFlagSource."""

    customFlagSource: list[CustomFlagSource] = Field(min_length=1)
