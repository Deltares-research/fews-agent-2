"""LocationSets.xml generator."""
from __future__ import annotations

from . import generic_xml_file
from ..schema.location_sets import LocationSets


def generate(model: LocationSets) -> str:
    return generic_xml_file.generate(model, "region/location_sets.xml.j2")
