"""ModifiersDisplay.xml — UI knobs for the Modifiers panel.

`createModifierButtons.modifierId[]` references modifier ids declared in
ModifierTypes.xml.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel
from .ids import ModifierId


class CreateModifierButtons(FewsModel):
    modifierId: list[ModifierId] = Field(default_factory=list)


class TimeSeriesModifiersDisplayConfig(FewsModel):
    showTimeShiftModifierButtons: bool | None = None
    showTablePanel: bool | None = None
    showChartPanel: bool | None = None
    defaultOperationType: str | None = None


class ModifierDisplay(FewsModel):
    """Root of ModifiersDisplay.xml (element is `modifierDisplay`)."""

    showImportButton: bool | None = None
    showExportButton: bool | None = None
    showCreateModifierButton: bool | None = None
    showApplyToButton: bool | None = None
    createModifierButtons: CreateModifierButtons | None = None
    timeSeriesModifiersDisplayConfig: TimeSeriesModifiersDisplayConfig | None = None
