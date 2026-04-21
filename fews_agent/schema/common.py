"""Shared compound types reused across FEWS file types.

These are the composable partials. Per CLAUDE.md §"composable partials":
each appears in many file types and should be defined once here, not
duplicated per generator.
"""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import ReadWriteMode, TimeSeriesType, TimeUnit, ValueType
from .ids import LocationId, LocationSetId, ModuleInstanceId, ParameterId, QualifierId


class FewsModel(BaseModel):
    """Strict base. Rejects unknown fields to catch typos early.

    `populate_by_name=True` lets us declare fields like `import_` with
    `alias="import"` to work around Python keywords in XML element names.
    Input accepts either the alias or the field name.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        frozen=False,
        populate_by_name=True,
    )


class TimeStep(FewsModel):
    """Either (unit[, multiplier]) or (id) — reference to a named timeStep.

    FEWS XSD allows both forms; exactly one must be set. The multiplier is
    optional in the unit form (FEWS defaults to 1 when omitted, matching
    tutorial usage like `<timeStep unit="day"/>`).
    """

    unit: TimeUnit | None = None
    multiplier: Annotated[int, Field(ge=1)] | None = None
    id: str | None = None

    @model_validator(mode="after")
    def _exactly_one_form(self) -> TimeStep:
        has_unit = self.unit is not None
        has_id = self.id is not None
        if has_unit and has_id:
            raise ValueError("timeStep: set either unit (+ optional multiplier) or id, not both")
        if not has_unit and not has_id:
            raise ValueError("timeStep: set unit (+ optional multiplier) or id")
        if has_id and self.multiplier is not None:
            raise ValueError("timeStep: multiplier only valid with the unit form")
        return self


class RelativeViewPeriod(FewsModel):
    """Time window relative to an anchor (forecast time, run time).

    start/end are `int | str`. int is the common case ("-10", 0). str is
    for FEWS runtime placeholders like `$STARTTIME$` / `$ENDTIME$` that
    the tutorial uses heavily in import + preprocess configs. Pydantic
    coerces numeric strings ("-10") to int; non-numeric stays str.

    `startOverrulable` / `endOverrulable` attributes appear on import and
    preprocess `relativeViewPeriod` elements — optional.

    This type doubles for the `<relativePeriod>` element inside
    `<startTimeShift>` (same XSD complexType, different element name).
    """

    unit: TimeUnit
    start: int | str
    end: int | str
    startOverrulable: bool | None = None
    endOverrulable: bool | None = None

    @model_validator(mode="after")
    def _start_le_end(self) -> RelativeViewPeriod:
        # Only check when both are concrete ints — placeholders skip the check.
        if isinstance(self.start, int) and isinstance(self.end, int):
            if self.start > self.end:
                raise ValueError(
                    f"relativeViewPeriod: start ({self.start}) > end ({self.end})"
                )
        return self


class TimeZone(FewsModel):
    """FEWS wraps the zone name in a timeZone element."""

    timeZoneName: str


class UnitMultiplier(FewsModel):
    """A simple {unit, multiplier} duration (no id form).

    Used for graceTime, eventExpiryTime, maxActionEventDuration, and
    similar period-like attributes. TimeStep is the superset (adds the
    named-id form) and is used where XSD allows both forms.
    """

    unit: TimeUnit
    multiplier: Annotated[int, Field(ge=1)]


class ExternUnit(FewsModel):
    """Declares the source-system unit for one parameter in an import."""

    parameterId: ParameterId
    unit: str
    cumulativeSum: bool = False


class ExtremeValueLimit(FewsModel):
    """One extreme-value bound.

    In XML each bound is an element with a `constantLimit` attribute:
    `<hardMax constantLimit="500"/>`. The XSD also supports other forms
    (referencing another series) which we can add as they appear.
    """

    constantLimit: float


class ExtremeValues(FewsModel):
    """Validation extremes; all bounds optional."""

    hardMax: ExtremeValueLimit | None = None
    hardMin: ExtremeValueLimit | None = None
    softMax: ExtremeValueLimit | None = None
    softMin: ExtremeValueLimit | None = None


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
    qualifierId: QualifierId | None = None
    synchLevel: int | None = None
    expiryTime: TimeStep | None = None
    ensembleId: str | None = None
    relativeViewPeriod: RelativeViewPeriod | None = None
    # Optional scaling factor. Seen in generalAdapterRun exportNetcdfActivity
    # timeSeriesSets to rescale a parameter on export; accepted by the XSD
    # elsewhere too. Numeric.
    multiplier: float | None = None

    @model_validator(mode="after")
    def _location_xor_set(self) -> TimeSeriesSet:
        has_loc = self.locationId is not None
        has_set = self.locationSetId is not None
        if has_loc == has_set:
            raise ValueError(
                "timeSeriesSet: supply exactly one of locationId or locationSetId"
            )
        return self
