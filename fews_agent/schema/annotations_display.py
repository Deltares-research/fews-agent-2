"""AnnotationsDisplay.xml — XSD has empty valueTypes/properties complex
types (stub). Emits ``<annotationsDisplay><valueTypes/><properties/></annotationsDisplay>``.

Distinct from:
- ``fews_agent.schema.annotation_display.AnnotationDisplay`` (permissions)
- ``fews_agent.schema.annotation_metadata_schema`` (properties schema)
"""
from __future__ import annotations

from .common import FewsModel


class AnnotationsDisplay(FewsModel):
    """Root of AnnotationsDisplay.xml — no fields (both children empty per XSD)."""
