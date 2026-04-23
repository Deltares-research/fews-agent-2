"""SampleMetadataSchema generator."""
from __future__ import annotations

from fews_agent.schema import SampleMetadataSchema

from .base import render


def generate(model: SampleMetadataSchema) -> str:
    return render("region/sample_metadata_schema.xml.j2", model)
