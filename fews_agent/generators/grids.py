"""Grids.xml generator."""
from __future__ import annotations

from . import generic_xml_file
from ..schema.grids import Grids


def generate(model: Grids) -> str:
    return generic_xml_file.generate(model, "region/grids.xml.j2")
