"""ModuleConfigProperties.xml — region-level <properties> referenced
from module config files via $key$ substitution.

Implements the full PropertiesComplexType (all six typed children —
string/int/float/double/bool/dateTime). Existing import-module Property
types stay untouched; these are local so there's no collision.

XSD allows arbitrary interleaving of the typed children. We emit in a
stable order (string, int, float, double, bool, dateTime); real configs
tend to group by type anyway.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import Field, model_validator

from .common import FewsModel


class _PropertyBase(FewsModel):
    """Shared structural base — key attribute + optional <description> child."""

    key: str
    description: str | None = None


class ConfigStringProperty(_PropertyBase):
    value: str


class ConfigIntProperty(_PropertyBase):
    value: int


class ConfigFloatProperty(_PropertyBase):
    # Decimal preserves source digits through the Jinja `xmlstr` filter.
    value: Decimal


class ConfigDoubleProperty(_PropertyBase):
    value: Decimal


class ConfigBoolProperty(_PropertyBase):
    value: bool


class ConfigDateTimeProperty(_PropertyBase):
    # XSD uses `date` + `time` attributes (both required) instead of `value`.
    date: str
    time: str


class ModuleConfigProperties(FewsModel):
    """Root of ModuleConfigProperties.xml."""

    description: str | None = None
    string: list[ConfigStringProperty] = Field(default_factory=list)
    # int/float/bool are Python reserved — use aliases so the XML tag matches.
    int_: list[ConfigIntProperty] = Field(default_factory=list, alias="int")
    float_: list[ConfigFloatProperty] = Field(default_factory=list, alias="float")
    double: list[ConfigDoubleProperty] = Field(default_factory=list)
    bool_: list[ConfigBoolProperty] = Field(default_factory=list, alias="bool")
    dateTime: list[ConfigDateTimeProperty] = Field(default_factory=list)

    @model_validator(mode="after")
    def _at_least_one_property(self) -> ModuleConfigProperties:
        if not any([
            self.string, self.int_, self.float_,
            self.double, self.bool_, self.dateTime,
        ]):
            raise ValueError(
                "moduleConfigProperties: at least one property entry required "
                "(string/int/float/double/bool/dateTime)"
            )
        return self
