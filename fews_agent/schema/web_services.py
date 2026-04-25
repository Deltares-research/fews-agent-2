"""WebServices.xml — FEWS web services configuration.

XSD root: ``webServices`` (WebServicesComplexType).

Nine optional siblings, each a deeply nested service-specific config:
  general, piRestService, wmsService, wfsService, ssdService,
  waterMlService, digitalDeltaService, operatingRequestService,
  webOperatorClientConfiguration.

Each service body has its own permissions, filters, formatters,
endpoints, etc. Per CLAUDE.md "``dict[str, Any]`` for subtrees deeper
than 3 nesting levels", we model each as a pass-through dict.
"""
from __future__ import annotations

from typing import Any

from .common import FewsModel


class WebServices(FewsModel):
    """Root of WebServices.xml."""

    general: dict[str, Any] | None = None
    piRestService: dict[str, Any] | None = None
    wmsService: dict[str, Any] | None = None
    wfsService: dict[str, Any] | None = None
    ssdService: dict[str, Any] | None = None
    waterMlService: dict[str, Any] | None = None
    digitalDeltaService: dict[str, Any] | None = None
    operatingRequestService: dict[str, Any] | None = None
    webOperatorClientConfiguration: dict[str, Any] | None = None
