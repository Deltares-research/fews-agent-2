"""Generator for FEWS files using the generic dict-body pattern.

Each caller passes its own template (with its own root element + xsd URL).
The template body renders `body` via the dict_to_xml filter.
"""
from __future__ import annotations

from fews_agent.schema import GenericXmlFile

from .base import render


def generate(model: GenericXmlFile, template_name: str) -> str:
    return render(template_name, model)
