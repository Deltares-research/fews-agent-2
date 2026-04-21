"""TimeSeriesDisplayConfig.xml — UI display defaults and color scales.

The top-level `<classBreaks>` is a container that holds one or more
inner `<classBreaks id="...">` entries. Each inner entry uses EITHER:

  - Discrete mode: one or more `<color color=".." opaquenessPercentage=".."
    lowerValue=".."/>` entries.
  - Gradient mode: `<lowerColor>`, `<upperColor>`, `<lowerOpaquenessPercentage>`,
    `<upperOpaquenessPercentage>`, plus multiple `<lowerValue>` entries.
    Can have repeated blocks of these for multi-range gradients.

Temperature-class entries in the tutorial use gradient mode with repeated
blocks. Our model supports both — a breaks entry holds optional color[]
list plus optional gradient fields; validation rejects entries with neither.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel
from .enums import TimeUnit
from .ids import ClassBreaksId


class GeneralDisplayConfig(FewsModel):
    """Top-level UI defaults. legendTextFunction uses FEWS tokens
    like `%PARAMETER_NAME%`, passed through verbatim."""

    legendTextFunction: str | None = None


class DefaultViewPeriod(FewsModel):
    unit: TimeUnit
    start: int
    end: int


class DiscreteColor(FewsModel):
    """One color step in discrete-color classBreaks."""

    color: str
    lowerValue: float
    opaquenessPercentage: int | None = Field(default=None, ge=0, le=100)


class ClassBreaksEntry(FewsModel):
    """One named color scale, either discrete or gradient.

    At least one of `color` (discrete steps) or gradient fields
    (lowerColor/upperColor + lowerValue list) must be supplied.
    """

    id: ClassBreaksId
    color: list[DiscreteColor] = Field(default_factory=list)
    lowerColor: list[str] = Field(default_factory=list)
    upperColor: list[str] = Field(default_factory=list)
    lowerOpaquenessPercentage: list[int] = Field(default_factory=list)
    upperOpaquenessPercentage: list[int] = Field(default_factory=list)
    lowerValue: list[float] = Field(default_factory=list)

    @model_validator(mode="after")
    def _has_some_content(self) -> ClassBreaksEntry:
        if not self.color and not (self.lowerColor or self.upperColor or self.lowerValue):
            raise ValueError(
                f"classBreaks '{self.id}': supply either discrete colors "
                f"or gradient fields"
            )
        return self


class ClassBreaks(FewsModel):
    """Container wrapping one or more named classBreaks entries."""

    classBreaks: list[ClassBreaksEntry] = Field(min_length=1)


class TimeSeriesDisplay(FewsModel):
    """Root of TimeSeriesDisplayConfig.xml."""

    generalDisplayConfig: GeneralDisplayConfig | None = None
    defaultViewPeriod: DefaultViewPeriod | None = None
    classBreaks: ClassBreaks | None = None
    version: str = "1.0"
