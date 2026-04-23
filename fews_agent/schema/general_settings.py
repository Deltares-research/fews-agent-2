"""GeneralSettings.xml — root-level defaults (warm-state search, forecast length)."""
from __future__ import annotations

from .common import FewsModel, RelativeViewPeriod, UnitMultiplier


class StateSettings(FewsModel):
    """XSD StateSettingsComplexType — both children optional."""

    defaultWarmStateSearchPeriod: RelativeViewPeriod | None = None
    defaultForecastLength: UnitMultiplier | None = None


class GeneralSettings(FewsModel):
    """Root of GeneralSettings.xml."""

    stateSettings: StateSettings | None = None
