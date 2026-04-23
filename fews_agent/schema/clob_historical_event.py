"""ClobHistoricalEvent.xml — the XML payload stored in the `eventXml`
CLOB column of the FEWS historical_events table. The XSD root element
is ``<historicalEvent>`` (same tag as a nested element inside the
region-chapter HistoricalEvents file — this is the *database-blob*
variant, not the region-config one)."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class ClobHistoricalEvent(FewsModel):
    """Root of the clob payload (XML element: ``<historicalEvent>``)."""

    parameterId: list[str] = Field(min_length=1)
    locationId: list[str] = Field(min_length=1)
