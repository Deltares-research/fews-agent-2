"""AnnotationDisplay.xml — per-action permissions for the annotation UI.

Note: different from the region-chapter ``AnnotationMetadataSchema.xml``
(which defines the property schema) and from ``annotationsDisplay.xsd``
(a separate, near-empty display stub).
"""
from __future__ import annotations

from .common import FewsModel


class AnnotationDisplay(FewsModel):
    """Root of AnnotationDisplay.xml."""

    createPermission: str | None = None
    editPermission: str | None = None
    deletePermission: str | None = None
