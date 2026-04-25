"""WebOperatorClient.xml — top-level Web OC configuration.

XSD WebOperatorClientComplexType is shallow at the root (``<general>`` +
``<components>``) but deep underneath (icons, login, helpMenu,
timeSettings, mapLayers, sidePanel, plus four kinds of display
component). We type only the two top-level slots and pass their bodies
through as ``dict[str, Any]``: there's no useful invariant to enforce
across the broad union of optional sub-trees, and dict_to_xml emits the
right XML whatever combination is supplied.
"""
from __future__ import annotations

from typing import Any

from .common import FewsModel


class WebOperatorClient(FewsModel):
    """Root of WebOperatorClient.xml.

    Both slots are XSD-optional. The empty ``<webOperatorClient/>`` is
    XSD-valid and useful as a no-op base config that overrides nothing.
    """

    general: dict[str, Any] | None = None
    components: dict[str, Any] | None = None
