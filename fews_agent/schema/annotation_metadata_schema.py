"""AnnotationMetadataSchema.xml — defines property value types and
properties for user-authored annotations.

Both <valueTypes> and <properties> are <choice maxOccurs="unbounded">
in the XSD, so the children can interleave freely. We model each as
parallel typed lists (emitted in a stable order: inline defs first,
csv-file refs last). This matches the common pattern in real configs
and keeps the model readable. Mixed ordering can be added later if a
real case demands it.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class AnnotationStringType(FewsModel):
    """<string id="..."/> — declares a plain-text value type."""

    id: str


class AnnotationEnumerationValue(FewsModel):
    code: str
    label: str | None = None
    constraintEnumerationId: str | None = None
    constraintEnumerationCode: str | None = None
    description: str


class AnnotationEnumeration(FewsModel):
    id: str
    value: list[AnnotationEnumerationValue] = Field(min_length=1)


class AnnotationEnumerationsCsvFile(FewsModel):
    file: str
    charset: str | None = None
    id: str
    code: str
    label: str
    description: str
    constraintEnumerationId: str | None = None
    constraintEnumerationCode: str | None = None


class AnnotationValueTypes(FewsModel):
    string: list[AnnotationStringType] = Field(default_factory=list)
    enumeration: list[AnnotationEnumeration] = Field(default_factory=list)
    enumerationsCsvFile: list[AnnotationEnumerationsCsvFile] = Field(default_factory=list)


class AnnotationProperty(FewsModel):
    id: str
    name: str | None = None
    valueTypeId: str
    description: str | None = None


class AnnotationPropertiesCsvFile(FewsModel):
    file: str
    charset: str | None = None
    id: str
    name: str | None = None
    description: str | None = None
    valueTypeId: str | None = None


class AnnotationProperties(FewsModel):
    property: list[AnnotationProperty] = Field(default_factory=list)
    propertiesCsvFile: list[AnnotationPropertiesCsvFile] = Field(default_factory=list)


class AnnotationMetadataSchema(FewsModel):
    """Root of AnnotationMetadataSchema.xml."""

    valueTypes: AnnotationValueTypes
    properties: AnnotationProperties
