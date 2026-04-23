"""AnnotationMetadataSchema generator."""
from __future__ import annotations

from fews_agent.schema import AnnotationMetadataSchema

from .base import render


def generate(model: AnnotationMetadataSchema) -> str:
    return render("region/annotation_metadata_schema.xml.j2", model)
