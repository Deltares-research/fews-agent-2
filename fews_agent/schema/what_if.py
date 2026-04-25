"""WhatIf.xml — persisted selections from a WhatIfTemplate.

Stores what was entered / selected / referenced when a user built a
what-if scenario from a template. FEWS emits this file at runtime; the
typed model lets agents author it directly too.

Reuses:
  - ``ModuleConfigProperties`` for the ``<properties>`` block
    (PropertiesComplexType — same XSD type).
  - ``Attribute`` from ``common`` for the ``AttributesSequence`` group
    embedded in each WhatIfLocation.
  - ``DateTimePair`` from ``archive_metadata`` for ``creationTime``.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from .common import Attribute, FewsModel
from .archive_metadata import DateTimePair
from .module_config_properties import ModuleConfigProperties


class SelectedModifier(FewsModel):
    """Attribute-only element — references a concrete modifier created by
    a system-activity descriptor for this what-if."""

    modifierTypeId: str
    modifierId: str
    systemActivityDescriptorId: str


class WhatIfLocation(FewsModel):
    id: str
    name: str
    x: Decimal
    y: Decimal
    z: Decimal | None = None
    parentLocationId: str | None = None
    attribute: list[Attribute] = Field(default_factory=list)


class WhatIfLocationSet(FewsModel):
    whatIfLocationSetId: str
    geoDatum: str
    location: list[WhatIfLocation] = Field(min_length=1)


class WhatIf(FewsModel):
    id: str
    userId: str
    templateId: str
    name: str | None = None
    description: str | None = None
    parentId: str | None = None
    referencedTemplateId: list[str] = Field(default_factory=list)
    properties: ModuleConfigProperties | None = None
    originalModifiers: list[SelectedModifier] = Field(default_factory=list)
    modifier: list[SelectedModifier] = Field(default_factory=list)
    locationSet: list[WhatIfLocationSet] = Field(default_factory=list)
    singleRunWhatIf: bool | None = None
    creationTime: DateTimePair | None = None
