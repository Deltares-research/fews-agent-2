"""Products.xml — typed wrapper around the broad UI-config XSD.

The Products XSD is wide and deeply nested; the tutorial uses every
shape with @attr-conventional dict input. Until field-by-field modelling
becomes load-bearing, we expose the same passthrough body shape used by
GenericXmlFile but as a dedicated typed class so SPECS can dispatch on
the spec rather than on a generic body.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel


class Products(FewsModel):
    """Root of Products.xml.

    Body is a list of single-key dicts (preserves child-element order
    across heterogeneous XSD `<choice maxOccurs="unbounded">`) or a flat
    dict; honors the `@attr` prefix convention via `dict_to_xml`.
    """

    body: list[dict[str, Any]] | dict[str, Any] = Field(default_factory=list)
