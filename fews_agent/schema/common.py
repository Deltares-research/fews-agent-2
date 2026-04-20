"""Shared compound types reused across FEWS file types.

These are the composable partials. Per CLAUDE.md §"composable partials":
each appears in many file types and should be defined once here, not
duplicated per generator.
"""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import ReadWriteMode, TimeSeriesType, TimeUnit, ValueType
from .ids import LocationId, LocationSetId, ModuleInstanceId, ParameterId


class FewsModel(BaseModel):
    """Strict base. Rejects unknown fields to catch typos early.

    Note: str_strip_whitespace is intentionally NOT set. Hand-authored FEWS
    XML can legitimately contain trailing whitespace inside text elements
    (e.g. tutorial has `<shortName>QR.sim </shortName>`). Stripping at the
    schema level would make our XML round-trip fail C14N comparison against
    the original. ID types still strip via their own StringConstraints.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=False,
    )


class TimeStep(FewsModel):
    """Either {unit, multiplier} or {id} (reference to a named timeStep).

    FEWS XSD allows both forms; exactly one must be set.
    """

    unit: TimeUnit | None = None
    multiplier: Annotated[int, Field(ge=1)] | None = None
    id: str | None = None

    @model_validator(mode="after")
    def _exactly_one_form(self) -> TimeStep:
        has_unit_form = self.unit is not None or self.multiplier is not None
        has_id_form = self.id is not None
        if has_unit_form and has_id_form:
            raise ValueError("timeStep: set either (unit, multiplier) or id, not both")
        if not has_unit_form and not has_id_form:
            raise ValueError("timeStep: set (unit, multiplier) or id")
        if has_unit_form and (self.unit is None or self.multiplier is None):
            raise ValueError("timeStep: unit and multiplier must both be set")
        return self


class RelativeViewPeriod(FewsModel):
    """Time window relative to an anchor (forecast time, run time).

    start/end are signed integers in `unit`s. start is typically negative
    (lookback), end is typically positive (lookahead).
    """

    unit: TimeUnit
    start: int
    end: int

    @model_validator(mode="after")
    def _start_le_end(self) -> RelativeViewPeriod:
        if self.start > self.end:
            raise ValueError(f"relativeViewPeriod: start ({self.start}) > end ({self.end})")
        return self


class TimeZone(FewsModel):
    """FEWS wraps the zone name in a timeZone element."""

    timeZoneName: str


class ExternUnit(FewsModel):
    """Declares the source-system unit for one parameter in an import."""

    parameterId: ParameterId
    unit: str
    cumulativeSum: bool = False


class ExtremeValues(FewsModel):
    """Validation extremes; all bounds optional."""

    hardMax: float | None = None
    hardMin: float | None = None
    softMax: float | None = None
    softMin: float | None = None


class TimeSeriesSet(FewsModel):
    """Shared substructure — appears in Import/Preprocess/DataProcessing
    modules, ValidationRuleSets, ThresholdValueSets, ModifierTypes, and
    ModelRunModule import activities.

    Invariant: exactly one of locationId / locationSetId is supplied.
    """

    moduleInstanceId: ModuleInstanceId
    valueType: ValueType
    parameterId: ParameterId
    locationId: LocationId | None = None
    locationSetId: LocationSetId | None = None
    timeSeriesType: TimeSeriesType
    timeStep: TimeStep
    readWriteMode: ReadWriteMode
    synchLevel: int | None = None
    expiryTime: TimeStep | None = None
    ensembleId: str | None = None
    relativeViewPeriod: RelativeViewPeriod | None = None

    @model_validator(mode="after")
    def _location_xor_set(self) -> TimeSeriesSet:
        has_loc = self.locationId is not None
        has_set = self.locationSetId is not None
        if has_loc == has_set:
            raise ValueError(
                "timeSeriesSet: supply exactly one of locationId or locationSetId"
            )
        return self
