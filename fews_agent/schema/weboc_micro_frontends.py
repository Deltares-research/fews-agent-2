"""WebOCMicroFrontEnds.xml — micro front-end registrations for the Web OC."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class WebOCMicroFrontEnd(FewsModel):
    id: str
    icon: str
    remoteId: str
    componentId: str
    display: str


class WebOCMicroFrontEnds(FewsModel):
    """Root of WebOCMicroFrontEnds.xml."""

    microFrontEnd: list[WebOCMicroFrontEnd] = Field(min_length=1)
