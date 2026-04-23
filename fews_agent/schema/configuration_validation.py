"""ConfigurationValidation.xml — cross-config reference-validation rules."""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel


class ConfigRef(FewsModel):
    """XSD choice: either refFileNamesFolder (alone) or a
    (refConfig + refElement + refAttribute) trio."""

    sourceElement: str
    sourceAttribute: str
    refFileNamesFolder: str | None = None
    refConfig: str | None = None
    refElement: str | None = None
    refAttribute: str | None = None
    refOptional: bool | None = None

    @model_validator(mode="after")
    def _ref_choice(self) -> ConfigRef:
        has_folder = self.refFileNamesFolder is not None
        has_trio = (
            self.refConfig is not None
            and self.refElement is not None
            and self.refAttribute is not None
        )
        if has_folder == has_trio:
            raise ValueError(
                "configRef: supply either refFileNamesFolder or "
                "(refConfig + refElement + refAttribute), not both/neither"
            )
        return self


class ConfigType(FewsModel):
    name: str
    configRef: list[ConfigRef] = Field(default_factory=list)


class ConfigurationValidation(FewsModel):
    """Root of ConfigurationValidation.xml."""

    configType: list[ConfigType] = Field(min_length=1)
    version: str = "1.0"
