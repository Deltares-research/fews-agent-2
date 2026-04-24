"""Shared compound types reused across FEWS file types.

These are the composable partials. Per CLAUDE.md §"composable partials":
each appears in many file types and should be defined once here, not
duplicated per generator.
"""
from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import ReadWriteMode, TimeSeriesType, TimeUnit, ValueType
from .ids import LocationId, LocationSetId, ModuleInstanceId, ParameterId, QualifierId


class FewsModel(BaseModel):
    """Strict base. Rejects unknown fields to catch typos early.

    `populate_by_name=True` lets us declare fields like `import_` with
    `alias="import"` to work around Python keywords in XML element names.
    Input accepts either the alias or the field name.

    str_strip_whitespace is deliberately NOT set: hand-authored FEWS XML
    can contain trailing whitespace inside text elements (the tutorial
    has `<shortName>QR.sim </shortName>`). Stripping at the schema layer
    would break C14N round-trip against the tutorial. ID types still
    strip via their own StringConstraints in ids.py.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=False,
        populate_by_name=True,
    )


class TimeStep(FewsModel):
    """Either (unit[, multiplier]) or (id) — reference to a named timeStep.

    FEWS XSD allows both forms; exactly one must be set. The multiplier is
    optional in the unit form (FEWS defaults to 1 when omitted, matching
    tutorial usage like `<timeStep unit="day"/>`).

    `multiplier` accepts `int | str`: int for concrete values, str for
    FEWS runtime placeholders like `$TIMESTEP$` that the tutorial uses in
    Preprocess/DataProcessing module templates.
    """

    unit: TimeUnit | None = None
    multiplier: int | str | None = None
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
        if isinstance(self.multiplier, int) and self.multiplier < 1:
            raise ValueError("timeStep: multiplier must be >= 1 when given as int")
        return self


class RelativeViewPeriod(FewsModel):
    """Time window relative to an anchor (forecast time, run time).

    start/end are `int | str`. int is the common case ("-10", 0). str is
    for FEWS runtime placeholders like `$STARTTIME$` / `$ENDTIME$` that
    the tutorial uses heavily in import + preprocess configs. Pydantic
    coerces numeric strings ("-10") to int; non-numeric stays str.

    start/end are both optional at the schema level — tutorial has
    `<relativeViewPeriod unit="hour" end="0" startOverrulable="true"/>`
    in at least one place, with no `start`. FEWS presumably treats
    missing bounds as unbounded or runtime-supplied.

    `startOverrulable` / `endOverrulable` attributes appear on import and
    preprocess `relativeViewPeriod` elements — optional.

    This type doubles for the `<relativePeriod>` element inside
    `<startTimeShift>` (same XSD complexType, different element name).
    """

    unit: TimeUnit
    start: int | str | None = None
    end: int | str | None = None
    startOverrulable: bool | None = None
    endOverrulable: bool | None = None

    @model_validator(mode="after")
    def _start_le_end(self) -> RelativeViewPeriod:
        # Only check when both are concrete ints — placeholders/None skip.
        if isinstance(self.start, int) and isinstance(self.end, int):
            if self.start > self.end:
                raise ValueError(
                    f"relativeViewPeriod: start ({self.start}) > end ({self.end})"
                )
        return self


class TimeZone(FewsModel):
    """FEWS wraps a zone declaration in a timeZone element.

    Accepts either a named zone (`<timeZoneName>GMT</timeZoneName>`) or
    an explicit offset (`<timeZoneOffset>+00:00</timeZoneOffset>`); both
    forms appear across tutorial imports.
    """

    timeZoneName: str | None = None
    timeZoneOffset: str | None = None


class UnitMultiplier(FewsModel):
    """A simple {unit, multiplier} duration (no id form).

    Used for graceTime, eventExpiryTime, maxActionEventDuration, and
    similar period-like attributes. TimeStep is the superset (adds the
    named-id form) and is used where XSD allows both forms.

    multiplier allows zero (coldState <startDate multiplier="0"/> means
    "start immediately at forecast time").
    """

    unit: TimeUnit
    multiplier: Annotated[int, Field(ge=0)]


class ExternUnit(FewsModel):
    """Declares the source-system unit for one parameter in an import."""

    parameterId: ParameterId
    unit: str
    cumulativeSum: bool = False


class SeasonCondition(FewsModel):
    """`<season>` with `<startMonthDay>` + `<endMonthDay>` children.

    monthDayType is an XSD-restricted gMonthDay with pattern ``--MM-DD``.
    Stored as raw strings so templates round-trip the source text byte
    for byte (gMonthDay can't be mapped to a native Python date without
    losing the literal form).
    """

    startMonthDay: str
    endMonthDay: str


class RelativeTime(FewsModel):
    """XSD RelativeTimeComplexType — ``value`` + ``unit`` attributes.

    Same shape as UnitMultiplier but uses ``value`` (XSD intStringType, so
    negatives are allowed) instead of ``multiplier``. Used for period
    lengths (objectiveAnalyzerDisplay) and peak influence periods.
    """

    value: int
    unit: TimeUnit
    description: str | None = None


class Period(FewsModel):
    """XSD PeriodComplexType — absolute window with startDate + endDate.

    Both are XSD ``dateTime`` (ISO-8601 string). Passed through as raw
    strings so the source digits round-trip byte for byte.
    """

    startDate: str
    endDate: str


class ValidPeriod(FewsModel):
    """XSD ValidPeriodComplexType — same shape as ``Period`` but with
    both ends optional, so a missing bound means 'open-ended'."""

    startDate: str | None = None
    endDate: str | None = None


class GeoPoint(FewsModel):
    """XSD GeoPointComplexType — (x, y, z?) numeric coordinates.

    x/y are XSD ``double``; z optional. Stored as str so numeric
    literals like ``"0"`` / ``"1.0"`` round-trip without
    float-formatting surprises.
    """

    x: str
    y: str
    z: str | None = None


class GridDefinition(FewsModel):
    """XSD GridDefinitionComplexType — rectangular grid over a GeoPoint
    upper-left corner with rows/columns/cellwidth/cellheight."""

    geoDatum: str
    upperLeftCorner: GeoPoint
    rows: int
    columns: int
    cellwidth: str
    cellheight: str


class CalendarTimeSpan(FewsModel):
    """XSD CalendarTimeSpanComplexType — attribute-only element.

    Wider unit set than ``TimeSpanComplexType``: adds ``day`` / ``week``
    / ``month`` / ``year`` on top of the base time units. Used for
    expiry/search time spans that need human-calendar units.
    """

    unit: str  # second/minute/hour/day/week/month/year
    multiplier: int | None = None
    divider: int | None = None


class Addition(FewsModel):
    """XSD AdditionComplexType — prefix/suffix for a generated filename.

    Choice between exactly one of simpleString / timeZeroFormattingString
    / currentTimeFormattingString. The last two hold a Java date-format
    pattern applied to the task's T0 / current time.
    """

    simpleString: str | None = None
    timeZeroFormattingString: str | None = None
    currentTimeFormattingString: str | None = None

    @model_validator(mode="after")
    def _one_branch(self) -> Addition:
        branches = [
            self.simpleString,
            self.timeZeroFormattingString,
            self.currentTimeFormattingString,
        ]
        if sum(b is not None for b in branches) != 1:
            raise ValueError(
                "Addition: exactly one of simpleString / "
                "timeZeroFormattingString / currentTimeFormattingString"
            )
        return self


class ExtremeValueLimit(FewsModel):
    """One extreme-value bound.

    In XML each bound is an element with a `constantLimit` attribute:
    `<hardMax constantLimit="500"/>`. The XSD also supports other forms
    (referencing another series) which we can add as they appear.

    `constantLimit` is stored as str to preserve the exact source text:
    tutorial values are integer-like ("500", "0"), which a Python float
    would emit as "500.0" / "0.0" and break C14N equality.
    """

    constantLimit: str


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

    # timeSeriesType/valueType/readWriteMode are logically enums, but
    # TransformationModule templates use placeholder tokens like
    # `$TIMESERIESTYPE$` in these fields. Typing as plain str keeps FEWS
    # runtime substitution intact; enum validity is checked by the XSD /
    # FEWS itself at runtime.
    moduleInstanceId: ModuleInstanceId
    valueType: str
    parameterId: ParameterId
    locationId: LocationId | None = None
    locationSetId: LocationSetId | None = None
    timeSeriesType: str
    timeStep: TimeStep
    readWriteMode: str
    qualifierId: QualifierId | None = None
    synchLevel: int | None = None
    expiryTime: TimeStep | None = None
    ensembleId: str | None = None
    relativeViewPeriod: RelativeViewPeriod | None = None
    # Optional scaling factor; str to preserve source text ("1" must not
    # become "1.0"). Same precision-preservation strategy as missingValue
    # and ExtremeValueLimit.constantLimit.
    multiplier: str | None = None

    @model_validator(mode="after")
    def _location_xor_set(self) -> TimeSeriesSet:
        has_loc = self.locationId is not None
        has_set = self.locationSetId is not None
        if has_loc == has_set:
            raise ValueError(
                "timeSeriesSet: supply exactly one of locationId or locationSetId"
            )
        return self


class TimeSeriesDataPoint(FewsModel):
    """XSD TimeSeriesDataComplexType — one <data> row inside a Variable's
    defined-data form. Mirrors the shape used by HistoricalEvents but
    lives here so any Variable consumer can reuse it.

    `value` is Decimal to preserve source digits through the xmlstr
    filter (same rationale as locations.x/y).
    """

    value: Any  # Decimal preferred; str accepted for placeholder tokens
    dateTime: str | None = None
    time: str | None = None
    monthDay: str | None = None
    dayofWeek: str | None = None
    monthofYear: str | None = None
    comment: str | None = None


class HarmonicComponent(FewsModel):
    """XSD HarmonicComponentComplexType — tidal-harmonic component.

    `name` is an enum of ~100 tidal constituent names (A0, M2, S2, ...);
    we pass through as str and let the XSD validate.
    """

    name: str
    amplitude: Any  # Decimal
    phase: Any  # Decimal


class DataVariable(FewsModel):
    """XSD VariableComplexType — choice between three mutually-exclusive forms.

    Named ``DataVariable`` (not ``Variable``) to avoid colliding with
    ``fews_agent.schema.transformation_module.Variable`` — a
    TransformationModule-specific wrapper carrying a ``variableId`` + a
    single ``timeSeriesSet``. Both map to ``VariableComplexType`` in
    their respective XSDs, but their Python shapes differ.

    Form A — timeSeriesSet (the common case):
        supply `timeSeriesSet` only.
    Form B — defined data:
        supply `data[]`, optionally with `timeStep`, `relativeViewPeriod`,
        `timeZone`. Do not set `timeSeriesSet` or `component`.
    Form C — harmonic components (tidal):
        supply `component[]` only.

    A model_validator enforces exactly one form is active.
    """

    # Form A
    timeSeriesSet: TimeSeriesSet | None = None
    # Form B
    timeStep: TimeStep | None = None
    relativeViewPeriod: RelativeViewPeriod | None = None
    data: list[TimeSeriesDataPoint] = Field(default_factory=list)
    timeZone: TimeZone | None = None
    # Form C
    component: list[HarmonicComponent] = Field(default_factory=list)

    @model_validator(mode="after")
    def _exactly_one_form(self) -> DataVariable:
        has_tss = self.timeSeriesSet is not None
        has_defined = bool(self.data) or any([
            self.timeStep is not None,
            self.relativeViewPeriod is not None,
            self.timeZone is not None,
        ])
        has_harmonic = bool(self.component)
        forms = sum([has_tss, has_defined, has_harmonic])
        if forms != 1:
            raise ValueError(
                "variable: supply exactly one form — timeSeriesSet, defined-data "
                "(data[] + optional timeStep/relativeViewPeriod/timeZone), or "
                "harmonic component[]"
            )
        if has_defined and not self.data:
            raise ValueError(
                "variable: defined-data form requires at least one <data> entry"
            )
        return self
