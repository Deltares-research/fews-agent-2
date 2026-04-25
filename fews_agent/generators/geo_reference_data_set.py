"""GeoReferenceDataSet generator."""
from __future__ import annotations

from fews_agent.schema import GeoReferenceDataSet

from .base import render


def generate(model: GeoReferenceDataSet) -> str:
    return render("region/geo_reference_data_set.xml.j2", model)
