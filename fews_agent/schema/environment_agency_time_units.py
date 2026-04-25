"""EnvironmentAgencyTimeUnits.xml — maps EA-style time-unit strings to milliseconds.

XSD root element is ``<timeUnits>`` (different from our existing
``fews_agent.schema.time_steps.TimeSteps``; this is the UK Environment
Agency import variant). Keeping the Python class name
``EnvironmentAgencyTimeUnits`` to avoid the collision.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class EnvironmentAgencyTimeUnit(FewsModel):
    # XSD enumerates ~40 values ("Unspecified", "1 s", "12 s", ...).
    # Pass through as plain str; the XSD will validate.
    unit: str
    milliseconds: int
    description: str | None = None


class EnvironmentAgencyTimeUnits(FewsModel):
    """Root of EnvironmentAgencyTimeUnits.xml (XML element: ``<timeUnits>``)."""

    timeUnit: list[EnvironmentAgencyTimeUnit] = Field(default_factory=list)
