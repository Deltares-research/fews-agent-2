"""SampleMetadataSchema.xml — defines value types and properties for
lab-sample metadata. Same structural shape as AnnotationMetadataSchema,
with extra dateTime/double value types and a scope (sample/value)
attribute on properties.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class SampleValueType(FewsModel):
    """Shared shape for <string>, <dateTime>, <double> value-type defs."""

    id: str


class SampleEnumerationValue(FewsModel):
    code: str
    label: str | None = None
    description: str


class SampleEnumeration(FewsModel):
    id: str
    value: list[SampleEnumerationValue] = Field(min_length=1)


class SampleEnumerationsCsvFile(FewsModel):
    file: str
    charset: str | None = None
    id: str
    code: str | None = None
    label: str | None = None
    description: str | None = None


class SampleValueTypes(FewsModel):
    string: list[SampleValueType] = Field(default_factory=list)
    dateTime: list[SampleValueType] = Field(default_factory=list)
    double: list[SampleValueType] = Field(default_factory=list)
    enumeration: list[SampleEnumeration] = Field(default_factory=list)
    enumerationsCsvFile: list[SampleEnumerationsCsvFile] = Field(default_factory=list)


class SampleProperty(FewsModel):
    id: str
    name: str | None = None
    valueTypeId: str
    # scope: "sample" | "value" (default "sample" per XSD), or a %COL% ref.
    scope: str | None = None
    description: str | None = None


class SamplePropertiesCsvFile(FewsModel):
    file: str
    charset: str | None = None
    id: str
    name: str | None = None
    description: str | None = None
    valueTypeId: str | None = None
    scope: str | None = None


class SampleProperties(FewsModel):
    property: list[SampleProperty] = Field(default_factory=list)
    propertiesCsvFile: list[SamplePropertiesCsvFile] = Field(default_factory=list)


class SampleMetadataSchema(FewsModel):
    """Root of SampleMetadataSchema.xml."""

    valueTypes: SampleValueTypes
    properties: SampleProperties
