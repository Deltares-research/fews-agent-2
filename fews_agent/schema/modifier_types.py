"""ModifierTypes.xml — registry of manual forecaster modifiers.

Each `timeSeriesModifier` declares a modifier that writes to a specific
(moduleInstance, parameter, location) target. The `<timeSeries>` block
inside a modifier is a lighter shape than the full TimeSeriesSet — it
omits timeSeriesType/timeStep/readWriteMode, which the XSD treats as
modifier-specific defaults rather than required.

`defaultValidTime` is modeled as a bool flag: the tutorial emits the bare
element `<defaultValidTime/>` to indicate its presence (value is
implicit); None omits it.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel
from .enums import DefaultTimeAnchor, ValueType
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
    id: ModifierId
    timeSeries: ModifierTimeSeries
    name: str | None = None
    applyToEnsemble: str | None = None
    defaultStartTime: DefaultTimeAnchor | None = None
    defaultEndTime: DefaultTimeAnchor | None = None
    defaultValidTime: bool = False
    resolveInWorkflow: bool | None = None
    resolveInPlots: bool | None = None
    editInPlots: bool | None = None


class ModifierTypes(FewsModel):
    """Root of ModifierTypes.xml."""

    timeSeriesModifier: list[TimeSeriesModifier] = Field(min_length=1)
    rollbackOverlappingModifiers: bool | None = None
