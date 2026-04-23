"""SampleProperties.xml — sample-time shift plus a <properties> block.

The <properties> inner block has the same PropertiesChoice shape used
by ModuleConfigProperties. Reusing the typed property models from that
module keeps the behaviour consistent (at-least-one enforcement lives
in ModuleConfigProperties; here <properties> always has at least one
entry, enforced at the sub-model level).
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel
from .module_config_properties import (
    ConfigBoolProperty,
    ConfigDateTimeProperty,
    ConfigDoubleProperty,
    ConfigFloatProperty,
    ConfigIntProperty,
    ConfigStringProperty,
)


class SamplePropertiesBlock(FewsModel):
    """Inner `<properties>` wrapper — PropertiesChoice group."""

    description: str | None = None
    string: list[ConfigStringProperty] = Field(default_factory=list)
    int_: list[ConfigIntProperty] = Field(default_factory=list, alias="int")
    float_: list[ConfigFloatProperty] = Field(default_factory=list, alias="float")
    double: list[ConfigDoubleProperty] = Field(default_factory=list)
    bool_: list[ConfigBoolProperty] = Field(default_factory=list, alias="bool")
    dateTime: list[ConfigDateTimeProperty] = Field(default_factory=list)

    @model_validator(mode="after")
    def _at_least_one_property(self) -> SamplePropertiesBlock:
        if not any([
            self.string, self.int_, self.float_,
            self.double, self.bool_, self.dateTime,
        ]):
            raise ValueError(
                "sampleProperties/properties: at least one property entry required"
            )
        return self


class SamplePropertiesFile(FewsModel):
    """Root of SampleProperties.xml.

    Named ``SamplePropertiesFile`` (not ``SampleProperties``) to avoid
    colliding with ``sample_metadata_schema.SampleProperties``, which
    models the inner ``<properties>`` block of SampleMetadataSchema.
    The XML root element is still ``<sampleProperties>``.
    """

    timeShiftMillis: int | None = None
    properties: SamplePropertiesBlock
