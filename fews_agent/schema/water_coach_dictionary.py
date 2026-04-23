"""WaterCoachDictionary.xml — word/definition list for WaterCoach training.

XSD root element is ``<dictionary>`` (not ``<waterCoachDictionary>``).
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class DictionaryEntry(FewsModel):
    word: str
    definition: str


class WaterCoachDictionary(FewsModel):
    """Root of WaterCoachDictionary.xml (XML element: ``<dictionary>``)."""

    entry: list[DictionaryEntry] = Field(default_factory=list)
