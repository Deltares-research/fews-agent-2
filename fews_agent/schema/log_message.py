"""LogMessage.xml — single <message> element with text content + metadata attrs.

XSD uses simpleContent extending nonEmptyStringType — the message body
is the element's text, not a child element.
"""
from __future__ import annotations

from .common import FewsModel


class LogMessage(FewsModel):
    """Root of LogMessage.xml (XML element: ``<message>``).

    ``text`` becomes the element's text content; the rest are attributes.
    """

    text: str
    userId: str | None = None
    topologyNodeId: str | None = None
    areaId: str | None = None
    templateId: str | None = None
    eventDate: str | None = None  # ISO 8601 date (YYYY-MM-DD)
    eventTime: str | None = None  # ISO 8601 time (HH:MM:SS[.sss])
