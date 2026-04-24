"""ModifiersDisplay.xml — UI knobs for the Modifiers panel.

`createModifierButtons.modifierId[]` references modifier ids declared in
ModifierTypes.xml.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel
from .ids import ModifierId


ModifiersSelection = Literal["topology", "filters"]


class CreateModifierButtons(FewsModel):
    modifierId: list[ModifierId] = Field(default_factory=list)


class DropDownMenuModifierItem(FewsModel):
    """One menu entry — id + ordered parameterId[] controlling which
    modifiers appear under it and in what order."""

    id: str
    parameterId: list[str] = Field(default_factory=list)


class DropDownMenuModifierDisplayOrder(FewsModel):
    modifier: list[DropDownMenuModifierItem] = Field(min_length=1)


class TimeSeriesModifiersDisplayConfig(FewsModel):
    showTimeShiftModifierButtons: bool | None = None
    showTablePanel: bool | None = None
    showChartPanel: bool | None = None
    defaultOperationType: str | None = None


class ModifierDisplay(FewsModel):
    """Root of ModifiersDisplay.xml (element is `modifierDisplay`).

    XSD sequence: showImportButton, showExportButton,
    rollbackModifierAfterDelete, showCreateModifierButton,
    showApplyToButton, showReRunButton, modifiersSelection,
    dropDownMenuDisplayOrder, createModifierButtons,
    timeSeriesModifiersDisplayConfig. All optional.
    """

    showImportButton: bool | None = None
    showExportButton: bool | None = None
    rollbackModifierAfterDelete: bool | None = None
    showCreateModifierButton: bool | None = None
    showApplyToButton: bool | None = None
    showReRunButton: bool | None = None
    modifiersSelection: ModifiersSelection | None = None
    dropDownMenuDisplayOrder: DropDownMenuModifierDisplayOrder | None = None
    createModifierButtons: CreateModifierButtons | None = None
    timeSeriesModifiersDisplayConfig: TimeSeriesModifiersDisplayConfig | None = None
