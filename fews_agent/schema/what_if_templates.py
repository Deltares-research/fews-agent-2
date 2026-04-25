"""WhatIfTemplates.xml — what-if dialog template definitions.

``valueTypes`` is an XSD ``choice maxOccurs="unbounded"`` group of nine
element kinds. Since the XSD does not constrain their order, we model
each kind as a separate list on ``WhatIfTemplateValueTypes`` and emit
them in a fixed order. Users wanting a specific emission order per
template can still split into multiple WhatIfTemplates definitions.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import (
    CalendarTimeSpan,
    FewsModel,
    RelativeViewPeriod,
    TimeStep,
)


ConfigFileType = Literal["cold state", "module dataset", "module parameter"]


class WhatIfTemplateEnumerationValue(FewsModel):
    code: str
    label: str | None = None


class WhatIfTemplateEnumeration(FewsModel):
    id: str
    default: str | None = None
    value: list[WhatIfTemplateEnumerationValue] = Field(min_length=1)


class TriggerProperty(FewsModel):
    code: str
    propertyId: str | None = None


class WhatIfTemplateMultiPropertyEnumerationValue(FewsModel):
    code: str
    label: str | None = None
    triggerProperty: list[TriggerProperty] = Field(min_length=1)


class WhatIfTemplateMultiPropertyEnumeration(FewsModel):
    id: str
    default: str | None = None
    value: list[WhatIfTemplateMultiPropertyEnumerationValue] = Field(min_length=1)


class WhatIfTemplateConfigFile(FewsModel):
    id: str
    type: ConfigFileType
    pattern: str
    hidePattern: bool | None = None
    default: str | None = None


class WhatIfTemplateStringValue(FewsModel):
    id: str
    default: str | None = None


class WhatIfTemplateIntValue(FewsModel):
    id: str
    default: int | None = None
    min: int | None = None
    max: int | None = None


class WhatIfTemplateDoubleValue(FewsModel):
    id: str
    default: float | None = None
    min: float | None = None
    max: float | None = None


class WhatIfTemplateBoolValue(FewsModel):
    id: str
    default: bool | None = None


class WhatIfTemplateDateTimeValue(FewsModel):
    id: str
    defaultDate: str | None = None
    defaultTime: str | None = None
    dateTimeFormat: str | None = None
    relativePeriod: RelativeViewPeriod | None = None
    cardinalTimeStep: TimeStep | None = None


class WhatIfTemplateTemplateId(FewsModel):
    """Inner ``whatIfTemplateId`` entry in ``valueTypes`` — carries both
    ``id`` (the value-type id) and ``templateId`` (reference to the
    target template)."""

    id: str
    templateId: str


class WhatIfTemplateValueTypes(FewsModel):
    enumeration: list[WhatIfTemplateEnumeration] = Field(default_factory=list)
    multiPropertyEnumeration: list[WhatIfTemplateMultiPropertyEnumeration] = Field(
        default_factory=list
    )
    configFile: list[WhatIfTemplateConfigFile] = Field(default_factory=list)
    string: list[WhatIfTemplateStringValue] = Field(default_factory=list)
    int_: list[WhatIfTemplateIntValue] = Field(default_factory=list, alias="int")
    double: list[WhatIfTemplateDoubleValue] = Field(default_factory=list)
    bool_: list[WhatIfTemplateBoolValue] = Field(default_factory=list, alias="bool")
    dateTime: list[WhatIfTemplateDateTimeValue] = Field(default_factory=list)
    whatIfTemplateId: list[WhatIfTemplateTemplateId] = Field(default_factory=list)


class WhatIfTemplateProperty(FewsModel):
    id: str
    valueTypeId: str
    name: str | None = None
    triggerPropertyId: str | None = None
    description: str | None = None


class WhatIfTemplateProperties(FewsModel):
    property: list[WhatIfTemplateProperty] = Field(min_length=1)


class SingleRunWhatIf(FewsModel):
    default: bool
    overRulable: bool | None = None


class WhatIfTemplate(FewsModel):
    id: str
    name: str
    whatIfExpiryTime: CalendarTimeSpan | None = None
    singleRunWhatIf: SingleRunWhatIf | None = None
    properties: WhatIfTemplateProperties | None = None
    modifierType: list[str] = Field(default_factory=list)
    defaultModifierType: str | None = None
    whatIfTemplateId: list[str] = Field(default_factory=list)


class WhatIfTemplates(FewsModel):
    valueTypes: WhatIfTemplateValueTypes | None = None
    whatIfTemplate: list[WhatIfTemplate] = Field(min_length=1)
