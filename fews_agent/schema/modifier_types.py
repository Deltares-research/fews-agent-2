"""ModifierTypes.xml — registry of manual forecaster modifiers.

Four modifier shapes are fully typed (tutorial uses these):
  - timeSeriesModifier: the common shape — writes into a single
    (moduleInstance, parameter, location) target
  - spatialCopyModifier: copies a source grid onto a target; carries
    multiple <timeSeries> blocks and an expiryTime
  - spatialProfileModifier: like spatialCopy but adds
    userDefinedDescriptionField + descriptiveFunctionGroups
  - modifiersGroup: UI grouping — a list of modifierIds under one label

The remaining 22 modifier variants (adjustQModifiers, attributeModifiers,
compoundModifier, constantValueModifier, copyModifiers, enumerationModifier,
highLowSurgeSelectionModifier, markUnreliableModifier, mergeSimpleModifiers,
mergeWeightedModifiers, missingValueModifier, moduleParameterModifier,
multipleModuleParameterModifier, optionModifier, priorityModifier,
ratingCurveModifiers, sampleHistoricalModifiers, singleValueModifier,
switchOptionModifier, timeShiftConstantModifiers, typicalProfileModifier,
unitHydrographModifiers) are accepted as ``list[dict]`` and rendered via
the shared ``dict_to_xml`` filter. Agents can author them by hand when
needed; each modifier kind has its own 50-200 line sub-tree in the XSD
so full typing is out of scope. The list field names match the XSD
element names directly.

The embedded <timeSeries> blocks across modifier kinds have different
shapes (see ModifierTimeSeries/SpatialCopyTimeSeries/
SpatialProfileTimeSeries). They're all lighter than the full
TimeSeriesSet the rest of the system uses.

`defaultValidTime` on timeSeriesModifier is modeled as a bool flag: the
tutorial emits the bare element `<defaultValidTime/>` to indicate its
presence (value is implicit); None / False omits it.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from .common import FewsModel, UnitMultiplier
from .enums import DefaultTimeAnchor, TimeUnit, ValueType
from .ids import LocationId, LocationSetId, ModifierId, ModuleInstanceId, ParameterId


class ModifierTimeSeries(FewsModel):
    """Target of a modifier — lighter than the full TimeSeriesSet.

    Invariant: exactly one of locationId / locationSetId is supplied.
    """

    moduleInstanceId: ModuleInstanceId
    valueType: ValueType
    parameterId: ParameterId
    locationId: LocationId | None = None
    locationSetId: LocationSetId | None = None

    @model_validator(mode="after")
    def _location_xor_set(self) -> ModifierTimeSeries:
        has_loc = self.locationId is not None
        has_set = self.locationSetId is not None
        if has_loc == has_set:
            raise ValueError(
                "modifier timeSeries: supply exactly one of locationId or locationSetId"
            )
        return self


class TimeSeriesModifier(FewsModel):
    # Attrs. `name` carries the human-readable label shown to the
    # operator; XSD requires it (use="required"), so Pydantic does too.
    id: ModifierId
    name: str
    # ModifierBase elements (XSD sequence, inherited)
    modifierTypeDescription: str | None = None
    expiryTime: UnitMultiplier | None = None
    expiryTimeDeletedModifiers: UnitMultiplier | None = None
    modifierCardinalTimeStep: dict[str, Any] | None = None
    userDefinedDescriptionField: list[dict[str, Any]] = Field(default_factory=list)
    whatIfModifierType: str | None = None
    createPermission: str | None = None
    # TimeSeriesModifierBase extension
    useLocationLongName: bool | None = None
    applyToDeterministicRun: bool | None = None
    applyToEnsemble: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce_apply_to_ensemble(cls, data):
        """Accept a bare string for backwards compat with single-ensemble inputs."""
        if isinstance(data, dict) and isinstance(data.get("applyToEnsemble"), str):
            data["applyToEnsemble"] = [data["applyToEnsemble"]]
        return data
    # TimeSeriesModifier extension
    timeSeries: ModifierTimeSeries
    onlyApplyLastModifier: bool | None = None
    mergeUnCommittedModifiers: bool | None = None
    referenceTimeSeries: list[dict[str, Any]] = Field(default_factory=list)
    softLimits: dict[str, Any] | None = None
    hardLimits: dict[str, Any] | None = None
    defaultStartTime: DefaultTimeAnchor | None = None
    defaultEndTime: DefaultTimeAnchor | None = None
    defaultValidTime: bool = False
    # `resolveInWorkflow` and `resolveInPlots` have no XSD `minOccurs="0"`,
    # so they're required. Pydantic enforces what the XSD enforces — no
    # silent defaults that would emit XSD-invalid XML.
    resolveInWorkflow: bool
    resolveInPlots: bool
    editInPlots: bool | None = None
    graphicalEditing: bool | None = None
    perEnsembleMember: bool | None = None
    createContinuousModifiers: bool | None = None


class SpatialCopyTimeSeries(FewsModel):
    """<timeSeries> inside spatialCopyModifier — moduleInstance + parameter + location."""

    moduleInstanceId: ModuleInstanceId
    parameterId: ParameterId
    locationId: LocationId


class SpatialCopyModifier(FewsModel):
    # Attrs
    id: ModifierId
    name: str | None = None
    # ModifierBase inherited elements (XSD sequence)
    modifierTypeDescription: str | None = None
    expiryTime: UnitMultiplier | None = None
    expiryTimeDeletedModifiers: UnitMultiplier | None = None
    modifierCardinalTimeStep: dict[str, Any] | None = None
    userDefinedDescriptionField: list[dict[str, Any]] = Field(default_factory=list)
    whatIfModifierType: str | None = None
    createPermission: str | None = None
    # SpatialModifier extension
    timeSeries: list[SpatialCopyTimeSeries] = Field(min_length=1)


class SpatialProfileTimeSeries(FewsModel):
    """<timeSeries> inside spatialProfileModifier — no location."""

    moduleInstanceId: ModuleInstanceId
    parameterId: ParameterId


class UserDefinedDescriptionField(FewsModel):
    """`<userDefinedDescriptionField id="..." descriptionField="..."/>`."""

    id: str
    descriptionField: str


class TimeSpan(FewsModel):
    """XSD TimeSpanComplexType — used inside descriptiveFunction and as
    the ``graceTime`` element in forecast-management TimeThresholds.

    XSD requires ``unit`` (timeUnitStringType). ``multiplier`` and
    ``divider`` are optional; supply at least one when the span is
    non-trivial. Tutorial usage always carries ``multiplier``, so it
    stays as the conventional default.
    """

    unit: TimeUnit
    multiplier: int | None = Field(default=None, ge=1)
    divider: int | None = Field(default=None, ge=1)


class DescriptiveFunction(FewsModel):
    """Element carries `function` and `ignoreMissings` as attributes,
    with optional <timeSpan> children for functions like
    movingAccumulationMax."""

    function: str
    ignoreMissings: bool | None = None
    timeSpan: list[TimeSpan] = Field(default_factory=list)


class DescriptiveFunctionGroup(FewsModel):
    name: str
    descriptiveFunction: list[DescriptiveFunction] = Field(default_factory=list)


class DescriptiveFunctionGroups(FewsModel):
    """Wrapper around zero-or-more <descriptiveFunctionGroup>.

    ``displayedcolumns`` selects which statistic columns appear in the
    display table — XSD enum (``statistics entire timeseries`` or the
    longer pre/post time-zero variant).
    """

    displayedcolumns: str | None = None
    descriptiveFunctionGroup: list[DescriptiveFunctionGroup] = Field(default_factory=list)


class SpatialProfileModifier(FewsModel):
    # Attrs
    id: ModifierId
    name: str | None = None
    # ModifierBase inherited elements (XSD sequence)
    modifierTypeDescription: str | None = None
    expiryTime: UnitMultiplier | None = None
    expiryTimeDeletedModifiers: UnitMultiplier | None = None
    modifierCardinalTimeStep: dict[str, Any] | None = None
    userDefinedDescriptionField: UserDefinedDescriptionField | None = None
    whatIfModifierType: str | None = None
    createPermission: str | None = None
    # Spatial profile extension
    timeSeries: list[SpatialProfileTimeSeries] = Field(min_length=1)
    descriptiveFunctionGroups: DescriptiveFunctionGroups | None = None


class ModifiersGroup(FewsModel):
    """UI grouping — a set of modifierId references labelled by `id`.

    Tutorial reuses existing modifier ids as group ids; treat as
    ModifierId since validator-wise they share the same namespace.
    """

    id: ModifierId
    modifierId: list[ModifierId] = Field(min_length=1)


class ModifierTypes(FewsModel):
    """Root of ModifierTypes.xml. At least one modifier of any kind.

    Root-level bool flags (all optional) from the XSD sequence:
    restoreModifiersWhenApprovingForecastRun, rollbackOverlappingModifiers,
    autoCommit, autoExtendExpiryTime.

    Four modifier kinds are typed (timeSeriesModifier, spatialCopyModifier,
    spatialProfileModifier, modifiersGroup); the other 22 variants are
    accepted as ``list[dict]`` passthroughs — see module docstring.
    """

    # Root-level flags
    restoreModifiersWhenApprovingForecastRun: bool | None = None
    rollbackOverlappingModifiers: bool | None = None
    autoCommit: bool | None = None
    autoExtendExpiryTime: bool | None = None
    # Typed modifier variants
    timeSeriesModifier: list[TimeSeriesModifier] = Field(default_factory=list)
    spatialCopyModifier: list[SpatialCopyModifier] = Field(default_factory=list)
    spatialProfileModifier: list[SpatialProfileModifier] = Field(default_factory=list)
    modifiersGroup: list[ModifiersGroup] = Field(default_factory=list)
    # Passthrough modifier variants (each element is a nested dict body
    # rendered via the dict_to_xml filter; XSD element names preserved).
    missingValueModifier: list[dict[str, Any]] = Field(default_factory=list)
    typicalProfileModifier: list[dict[str, Any]] = Field(default_factory=list)
    constantValueModifier: list[dict[str, Any]] = Field(default_factory=list)
    singleValueModifier: list[dict[str, Any]] = Field(default_factory=list)
    enumerationModifier: list[dict[str, Any]] = Field(default_factory=list)
    markUnreliableModifier: list[dict[str, Any]] = Field(default_factory=list)
    adjustQModifiers: list[dict[str, Any]] = Field(default_factory=list)
    timeShiftConstantModifiers: list[dict[str, Any]] = Field(default_factory=list)
    sampleHistoricalModifiers: list[dict[str, Any]] = Field(default_factory=list)
    mergeSimpleModifiers: list[dict[str, Any]] = Field(default_factory=list)
    compoundModifier: list[dict[str, Any]] = Field(default_factory=list)
    highLowSurgeSelectionModifier: list[dict[str, Any]] = Field(default_factory=list)
    switchOptionModifier: list[dict[str, Any]] = Field(default_factory=list)
    optionModifier: list[dict[str, Any]] = Field(default_factory=list)
    moduleParameterModifier: list[dict[str, Any]] = Field(default_factory=list)
    priorityModifier: list[dict[str, Any]] = Field(default_factory=list)
    multipleModuleParameterModifier: list[dict[str, Any]] = Field(default_factory=list)
    unitHydrographModifiers: list[dict[str, Any]] = Field(default_factory=list)
    mergeWeightedModifiers: list[dict[str, Any]] = Field(default_factory=list)
    ratingCurveModifiers: list[dict[str, Any]] = Field(default_factory=list)
    attributeModifiers: list[dict[str, Any]] = Field(default_factory=list)
    copyModifiers: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _at_least_one_modifier(self) -> ModifierTypes:
        if not (
            self.timeSeriesModifier
            or self.spatialCopyModifier
            or self.spatialProfileModifier
            or self.modifiersGroup
            or self.missingValueModifier
            or self.typicalProfileModifier
            or self.constantValueModifier
            or self.singleValueModifier
            or self.enumerationModifier
            or self.markUnreliableModifier
            or self.adjustQModifiers
            or self.timeShiftConstantModifiers
            or self.sampleHistoricalModifiers
            or self.mergeSimpleModifiers
            or self.compoundModifier
            or self.highLowSurgeSelectionModifier
            or self.switchOptionModifier
            or self.optionModifier
            or self.moduleParameterModifier
            or self.priorityModifier
            or self.multipleModuleParameterModifier
            or self.unitHydrographModifiers
            or self.mergeWeightedModifiers
            or self.ratingCurveModifiers
            or self.attributeModifiers
            or self.copyModifiers
        ):
            raise ValueError(
                "modifierTypes: supply at least one modifier of any kind"
            )
        return self
