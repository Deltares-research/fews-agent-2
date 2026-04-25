"""IdMapDescriptors.xml — registry of idMap ids.

The XSD is marked "Obsolete schema" in a comment, but still compiles and
some tutorial configs reference this file. Fields:

  - <idMapDescriptor id="..." name="..."> with optional <description>

Root attribute `version` is fixed="1.0" per XSD, so the model supplies
the default.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel
from .ids import IdMapId


class IdMapDescriptor(FewsModel):
    id: IdMapId
    name: str | None = None
    description: str | None = None


class IdMapDescriptors(FewsModel):
    version: str = "1.0"
    idMapDescriptor: list[IdMapDescriptor] = Field(min_length=1)
