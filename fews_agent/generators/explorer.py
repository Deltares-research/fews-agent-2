"""Explorer.xml generator."""
from __future__ import annotations

from . import generic_xml_file
from ..schema.explorer import Explorer


def generate(model: Explorer) -> str:
    return generic_xml_file.generate(model, "system/explorer.xml.j2")
