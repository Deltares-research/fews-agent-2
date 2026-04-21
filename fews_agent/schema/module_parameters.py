"""ModuleParameters — model-specific parameters (e.g. Raven, wflow).

Lives in ModuleParFiles/. Uses the FEWS PI schema namespace
(`http://www.wldelft.nl/fews/PI`), not the main FEWS namespace, and the
schema `pi_modelparameters.xsd`.

Each parameter carries exactly one of boolValue / stringValue /
doubleValue / intValue as a child element. Values often contain FEWS
runtime placeholders like `@BlockRavenCustomOutput@` which pass through
verbatim.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel
from .ids import ModuleParameterGroupId, ModuleParameterId


class ModuleParameter(FewsModel):
    """One parameter — exactly one value field set."""

    id: ModuleParameterId
    boolValue: str | None = None
    stringValue: str | None = None
    doubleValue: str | None = None
    intValue: str | None = None

    @model_validator(mode="after")
    def _exactly_one_value(self) -> ModuleParameter:
        set_fields = [
            name for name in ("boolValue", "stringValue", "doubleValue", "intValue")
            if getattr(self, name) is not None
        ]
        if len(set_fields) != 1:
            raise ValueError(
                f"parameter '{self.id}': set exactly one of boolValue, "
                f"stringValue, doubleValue, intValue (got: {set_fields or 'none'})"
            )
        return self


class ModuleParameterGroup(FewsModel):
    id: ModuleParameterGroupId
    name: str | None = None
    model: str | None = None
    parameter: list[ModuleParameter] = Field(min_length=1)


class ModuleParameters(FewsModel):
    """Root of a ModuleParFiles/<X>.xml (root element is `parameters`)."""

    group: list[ModuleParameterGroup] = Field(min_length=1)
    modifierType: str | None = None
    version: str = "1.5"
