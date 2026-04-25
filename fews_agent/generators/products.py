"""Products.xml generator — wraps the typed Products body."""
from __future__ import annotations

from . import generic_xml_file
from ..schema.products import Products


def generate(model: Products) -> str:
    return generic_xml_file.generate(model, "region/products.xml.j2")
