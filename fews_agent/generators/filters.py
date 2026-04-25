"""Filters.xml generator."""
from __future__ import annotations

from . import generic_xml_file
from ..schema.filters import Filters


def generate(model: Filters) -> str:
    return generic_xml_file.generate(model, "region/filters.xml.j2")
