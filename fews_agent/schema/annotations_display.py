"""AnnotationsDisplay.xml — XSD has empty valueTypes/properties complex
types (stub). Emits ``<annotationsDisplay><valueTypes/><properties/></annotationsDisplay>``.

Distinct from:
- ``fews_agent.schema.annotation_display.AnnotationDisplay`` (permissions)
- ``fews_agent.schema.annotation_metadata_schema`` (properties schema)
"""
from __future__ import annotations

from .common import FewsModel


class AnnotationsDisplay(FewsModel):
    """Root of AnnotationsDisplay.xml. Both children are empty elements
    per XSD; kept as bool flags for consistency with the gap-audit
    (default True — element always emitted as required by XSD)."""

    valueTypes: bool = True
    properties: bool = True
