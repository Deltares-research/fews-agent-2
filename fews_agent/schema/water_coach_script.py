"""WaterCoachScript.xml — Water Coach training/exercise script.

XSD root: ``script`` (scriptType, defined in waterCoachScript.xsd).

Structurally a script has an optional title/timeZone, a required
``dataStart`` (dateTimeType: date+time attrs), optional dataStop /
displayStart / scriptStart / scriptStop, then a choice of stories or
workflow[], and optional forecastTable / forecastNote /
dictionaryFiles.

The frame/story/forecastTable subtrees are deeply nested with i18n
attributes, condition operators, and HTML-form-like cell shapes. Per
CLAUDE.md "``dict[str, Any]`` for subtrees deeper than 3 nesting
levels" we model the top-level structure with typed dateTime wrappers
and pass through stories / workflow / forecastTable / forecastNote /
dictionaryFiles as dicts.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel


class WaterCoachDateTime(FewsModel):
    """XSD dateTimeType — attribute-only ``date`` + ``time``."""

    date: str
    time: str


class WaterCoachTimeZone(FewsModel):
    """XSD timeZoneType — choice of offset or name (one element)."""

    offset: str | None = None
    name: str | None = None


class WaterCoachScript(FewsModel):
    """Root of WaterCoachScript.xml (XSD root element name: ``script``)."""

    title: str | None = None
    timeZone: WaterCoachTimeZone | None = None
    dataStart: WaterCoachDateTime
    dataStop: WaterCoachDateTime | None = None
    displayStart: WaterCoachDateTime | None = None
    scriptStart: WaterCoachDateTime | None = None
    scriptStop: WaterCoachDateTime | None = None
    # Choice (0..1): stories | workflow[]
    stories: dict[str, Any] | None = None
    workflow: list[dict[str, Any]] = Field(default_factory=list)
    # Trailing optionals
    forecastTable: dict[str, Any] | None = None
    forecastNote: dict[str, Any] | None = None
    dictionaryFiles: dict[str, Any] | None = None
