"""LocationSets.xml — typed wrapper around the broad locationSets XSD.

LocationSets is a registry of named location groupings with several
constructor styles (csvFile, attributeFile, idContains, ...). Body uses
the @attr-conventional dict shape via `dict_to_xml`.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel


class LocationSets(FewsModel):
    """Root of LocationSets.xml."""

    body: list[dict[str, Any]] | dict[str, Any] = Field(default_factory=list)
