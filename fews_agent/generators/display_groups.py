"""DisplayGroups.xml generator."""
from __future__ import annotations

from . import generic_xml_file
from ..schema.display_groups import DisplayGroups


def generate(model: DisplayGroups) -> str:
    return generic_xml_file.generate(model, "system/display_groups.xml.j2")
