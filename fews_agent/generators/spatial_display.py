"""SpatialDisplay.xml generator."""
from __future__ import annotations

from . import generic_xml_file
from ..schema.spatial_display import SpatialDisplay


def generate(model: SpatialDisplay) -> str:
    return generic_xml_file.generate(model, "display/spatial_display.xml.j2")
