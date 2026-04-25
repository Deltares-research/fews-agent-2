"""WhatIfScenarioFilters.xml — config for the what-if filters tab.

Fixed ``version="1.1"``. Bundles string enumerations + properties the
user can edit in the What-If dialog, plus optional variable sets and
config-file references.

The ``configFiles`` subtree comes from ``whatIfScenario.xsd`` — same
``ConfigComplexType`` reused by whatIfScenario itself. Models in this
file cover the full tree (ModuleParameterFiles, ModuleDataSetFiles,
inline ModuleParameters with typed data choices) so whatIfScenario can
reuse them when it's promoted from the passthrough next.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from .common import ConfigFile, DataVariable, FewsModel


class WhatIfFilterStringEnumeration(FewsModel):
    """``<stringEnumeration id="..."><string>...</string>+</stringEnumeration>``.

    ``string`` is a Python keyword-adjacent built-in; the XSD uses it as
    an element name so the Python field keeps the name verbatim — at
    most annoying to read, but no keyword collision."""

    id: str
    string: list[str] = Field(min_length=1)


class WhatIfFilterEnumerations(FewsModel):
    stringEnumeration: list[WhatIfFilterStringEnumeration] = Field(min_length=1)


class WhatIfFilterProperty(FewsModel):
    """One editable property. References an enumeration by id for its
    allowed values."""

    key: str
    enumerationId: str


class WhatIfFilterProperties(FewsModel):
    property: list[WhatIfFilterProperty] = Field(min_length=1)


class VariableSets(FewsModel):
    variable: list[DataVariable] = Field(min_length=1)


class WhatIfModuleParameterBoolData(FewsModel):
    value: bool
    allowAdjust: bool | None = None


class WhatIfModuleParameterIntData(FewsModel):
    value: int
    maxVal: int
    minVal: int
    allowAdjust: bool | None = None
    stepSize: int | None = None


class WhatIfModuleParameterDoubleData(FewsModel):
    value: Decimal
    maxVal: Decimal
    minVal: Decimal
    allowAdjust: bool | None = None
    stepSize: Decimal | None = None


class WhatIfModuleParameterData(FewsModel):
    """XSD choice — exactly one of booleanData / intData / doubleData /
    stringData. Each is a simpleContent extension: ``value`` field plus
    attributes."""

    booleanData: WhatIfModuleParameterBoolData | None = None
    intData: WhatIfModuleParameterIntData | None = None
    doubleData: WhatIfModuleParameterDoubleData | None = None
    stringData: str | None = None

    @model_validator(mode="after")
    def _one_of(self) -> WhatIfModuleParameterData:
        variants = [self.booleanData, self.intData, self.doubleData, self.stringData]
        if sum(v is not None for v in variants) != 1:
            raise ValueError(
                "moduleParameter data: supply exactly one of booleanData / "
                "intData / doubleData / stringData"
            )
        return self


class WhatIfModuleParameter(FewsModel):
    name: str
    data: WhatIfModuleParameterData
    comment: str | None = None
    id: str | None = None


class WhatIfModuleParameters(FewsModel):
    """Inline moduleParameters block (same content as a ModuleParFiles XML
    would hold, but embedded)."""

    id: str
    param: list[WhatIfModuleParameter] = Field(min_length=1)
    description: str | None = None


class ModuleParameterFiles(FewsModel):
    moduleParameterFile: list[ConfigFile] = Field(min_length=1)


class ModuleDataSetFiles(FewsModel):
    moduleDataSetFile: list[ConfigFile] = Field(min_length=1)


class WhatIfConfigFiles(FewsModel):
    """XSD ConfigComplexType (declared in whatIfScenario.xsd, reused by
    this file's ``configFiles`` element and by whatIfScenario's).
    ``hideModuleDataSetFilesPanel`` / ``hideModuleParameterFilesPanel``
    are XSD ``emptyElement`` flags — modelled as optional bools that
    render an empty ``<hide.../>`` when True.
    """

    moduleParameterFiles: ModuleParameterFiles | None = None
    moduleDataSetFiles: ModuleDataSetFiles | None = None
    hideModuleDataSetFilesPanel: bool | None = None
    moduleParameters: WhatIfModuleParameters | None = None
    hideModuleParameterFilesPanel: bool | None = None
    piModelParametersContent: str | None = None


class WhatIfScenarioFilters(FewsModel):
    """Root of WhatIfScenarioFilters.xml. Required attributes: name, version."""

    name: str
    version: Literal["1.1"] = "1.1"
    id: str | None = None
    description: str | None = None
    propertiesTabVisible: bool | None = None
    enumerations: WhatIfFilterEnumerations | None = None
    properties: WhatIfFilterProperties | None = None
    variableSets: VariableSets | None = None
    configFiles: WhatIfConfigFiles | None = None
    relativeT0DateFormat: bool | None = None
