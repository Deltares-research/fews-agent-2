"""SamplePropertiesFile generator (produces SampleProperties.xml)."""
from __future__ import annotations

from fews_agent.schema import SamplePropertiesFile

from .base import render


def generate(model: SamplePropertiesFile) -> str:
    return render("region/sample_properties.xml.j2", model)
