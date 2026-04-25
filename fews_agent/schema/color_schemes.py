"""ColorSchemes.xml — predefined + custom color palette schemes.

XSD root is ``<schemes>`` with one or more ``<scheme>`` children. Each
scheme has a fixed sequence of ~312 named ``<predefinedColorKey>`` slots
plus an optional ``<customColorKeys>`` list of free-form
``<key key="..." color="..."/>`` entries.

Modelling tradeoff: enumerating 312 optional fields would be unwieldy
with no validation upside (each is a single optional ``color`` attr). We
keep ``predefinedColorKeys`` as a ``dict[str, str | None]`` (name → hex
color, or None to declare the element with no attribute), and emit them
in canonical XSD order via a constant list in the template. Unknown keys
are XSD-validated at render time.

Custom color keys are typed because their shape is small and free-form.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel


class CustomColorKey(FewsModel):
    """XSD CustomColorKeyComplexType — ``<key key="..." color="..."/>``."""

    key: str
    color: str | None = None


class Scheme(FewsModel):
    """One ``<scheme>`` — a complete color palette named by ``name``.

    XSD ColorSchemeComplexType:
      sequence:
        - predefinedColorKeys (required, the giant fixed-order list)
        - customColorKeys (optional)
      attributes: name (required)

    ``predefinedColorKeys`` is a dict-passthrough: keys are XSD element
    names (e.g. ``"alertYellow"``, ``"caret"``, ``"chartBackground"``);
    values are the hex color string (no leading ``#``) or ``None`` to
    emit ``<x/>``. The template emits in the canonical XSD order from
    PREDEFINED_COLOR_KEY_ORDER and silently drops keys whose value is
    ``None`` from being templated unless explicitly desired.
    """

    name: str
    predefinedColorKeys: dict[str, Any] = Field(default_factory=dict)
    customColorKeys: list[CustomColorKey] = Field(default_factory=list)


class ColorSchemes(FewsModel):
    """Root of ColorSchemes.xml (``<schemes>``)."""

    scheme: list[Scheme] = Field(min_length=1)
    version: str | None = None


# Canonical XSD-sequence order of every named element inside
# PredefinedColorKeysComplexType. Pulled from colorSchemes.xsd. The
# template iterates this list so emitted XML always matches XSD order.
PREDEFINED_COLOR_KEY_ORDER: tuple[str, ...] = (
    "alertYellow", "alternateRow", "base", "blankIcon", "blueGray",
    "border", "borderActive", "borderButton", "borderDragging",
    "borderHighlight", "borderInactive", "buttonPressed", "buttonRollover",
    "caret", "cellCheckboxBackground", "chartBackground",
    "chartPanelValueMarker", "classBreakDefaultGrad1",
    "classBreakDefaultGrad2", "colorChooser", "control", "correlationItem",
    "correlationItemLabel", "defaultArrow", "defaultLine",
    "defaultMapBackground", "desktop", "desktopBackground",
    "doubleMassCurveValueMarker", "dropLine", "dummy",
    "errorMessageForeground", "etchedBorderHighlight", "etchedBorderShadow",
    "etchedSelectionBorderHighlight", "etchedSelectionBorderShadow",
    "flagBarBackground", "floatingForeground", "flowDomainMarker",
    "forecastListBoxTitle", "generalBackground", "generalBackgroundActive",
    "generalBackgroundDisabled", "generalBackgroundInactive",
    "generalBackgroundSelected", "generalDisabled", "generalDragging",
    "generalFocus", "generalForeground", "generalForegroundDisabled",
    "generalForegroundDocking", "generalForegroundInactive",
    "generalHighlight", "generalLight", "generalShadow", "generalShadowDark",
    "generalShadowDisabled", "green", "gridContour",
    "gridDisplayCompassRoseBorder", "gridDisplayCompassRoseLeftHalf",
    "gridDisplayCompassRoseRightHalf", "gridDisplayComponentBorder",
    "gridDisplayDefaultCircleBorder", "gridDisplayEmptyImage",
    "gridDisplayScaleBarSegmentEven", "gridDisplayScaleBarSegmentOdd",
    "gridDisplaySelectionForeground", "gridDisplaySelectionRectangle",
    "gridDisplaySketchPoint", "gridDisplayXorAlternation",
    "gridExcluded1", "gridExcluded2", "gridExcluded3", "gridLines",
    "hash", "highlightedDateTick", "highlightedDateTickMarker", "iconLine",
    "info", "infoBlue", "labelBackground", "labelForeground",
    "locationResultsBorder", "longitudinalValueMarker", "lookupRuleDefault",
    "mapLabelBackground", "mapLabelCurrentTime", "mapSelectionHighlight",
    "mapSelectionHighlightAlternate", "mapTrackCurrentTime", "mapTrackLine",
    "menu", "modelStatusFailedBackground", "modelStatusRunningBackground",
    "modelStatusSuccessfulBackground", "modelUserProfileBackground",
    "modelValueSetBackground", "modelValueTunedBackground", "modifierLocked",
    "modifierPartlyActive", "orange", "originalValueMarker",
    "panelBackground", "pcaValueMarker", "percentageDomainMarker",
    "plotAnnotationForeground", "plotAxisLabel", "plotBackground",
    "plotGridLine", "plotLabel", "plotLegendLabel", "plotLegendLabelSelected",
    "plotLongitudinalMaximum", "plotLongitudinalMinimum",
    "plotLongitudinalRiverBed", "plotLongitudinalValue",
    "plotLongitudinalValueMarker", "plotSlideBackground", "plotTickLabel",
    "plotTickMark", "plotUnitInside", "plotUnitOutside",
    "plotWhatIfAxisLabel", "plotWhatIfTickLabel", "plotWhatIfTickMark",
    "polygon", "polygonSelected", "rainDomainMarker", "red",
    "scalarPlotMarker", "scatterPlotSelectionBackground",
    "scenarioEditorDialogBackground", "scenarioEditorTitleBackground",
    "scrollbar", "selectionBackground", "selectionBorder",
    "selectionBorderBackground", "selectionForeground", "separatorForeground",
    "shapeDefaultBackground", "shapeFillColor", "shapeIconFill",
    "shapeIconLine", "sliderPanelBackgroundChanged", "sliderThumb",
    "sortIcon", "statisticsXyEditable", "statisticsXyNonEditable",
    "statusBarCapacity", "statusBarCapacityWarning", "statusBarConnecting",
    "statusBarFailover", "statusBarForeground",
    "statusBarIndexingBackground", "statusBarLabelHoverColor",
    "statusBarLoggedOff", "statusBarLoggedOn", "statusBarOkForeground",
    "statusBarProgress", "statusBarFinished", "statusBarProgressOc",
    "statusBarRollingBarrel", "statusBarSynchronising",
    "statusBarTimePausedBackground", "tableBackground", "tableCellBackground",
    "tableCellBoxWhiskerCategoryBackground",
    "tableCellBoxWhiskerValuesBackground", "tableCellCalibrationBackground",
    "tableCellCalibrationBackgroundChanged", "tableCellCalibrationForeground",
    "tableCellCalibrationForegroundSelected", "tableCellChangedAndCommitted",
    "tableCellChangedAndUncommitted", "tableCellChangedBackground",
    "tableCellChangedForeground", "tableCellColorPendingBackground",
    "tableCellColorUnknownBackground", "tableCellColumnHeaderBackground",
    "tableCellColumnHeaderForeground", "tableCellColumnHeaderIdForeground",
    "tableCellConfigActiveBackground", "tableCellConfigActiveForeground",
    "tableCellConfigInactiveBackground", "tableCellConfigInactiveForeground",
    "tableCellDashedBorder", "tableCellDateBackground",
    "tableCellDateBeforeTzeroBackground", "tableCellDateMidnightBackground",
    "tableCellDateText", "tableCellDateTextInvalidDate",
    "tableCellDisabledBackground", "tableCellEditableBackground",
    "tableCellEditableMissingBackground", "tableCellFilteredBackground",
    "tableCellForecastExpiredForeground", "tableCellForeground",
    "tableCellHeaderBackground", "tableCellLineBorder",
    "tableCellNeverImportedBackground", "tableCellNotEditableBackground",
    "tableCellRunInfoRowSelectedBackground", "tableCellRunningBackground",
    "tableCellSavedForeground", "tableCellSelectedBackground",
    "tableCellSelectedForeground", "tableCellSelectionBorder",
    "tableCellTimeSeriesBorder", "tableRowTabBackground", "text",
    "textBackground", "textBorder", "textDisabled", "textForeground",
    "textForegroundDisabled", "textHighlight", "textSelected",
    "thresholdAttributeMissingValue", "thresholdAttributeNoCrossing",
    "thresholdDefaultClassBreak", "thresholdSkillScoreMatching",
    "thresholdSkillScoreMissingForecast",
    "thresholdSkillScoreMissingObserved",
    "thresholdSkillScoreMissingObservedNoFalseAlarm", "thumb",
    "thumbnailDialogLineBorder", "tick", "timeNavigationStartDay",
    "timeSeriesCalibrationLabelForeground", "timeSeriesCompare1",
    "timeSeriesCompare2", "timeSeriesDefault",
    "timeSeriesDialogColumnHeaderColor", "timeSeriesFilteredBackground",
    "timeSeriesGroupBasisStatistics", "timeSeriesGroupCompletedDoubtful",
    "timeSeriesGroupCompletedReliable", "timeSeriesGroupCompletedUnreliable",
    "timeSeriesGroupCorrectedDoubtful", "timeSeriesGroupCorrectedReliable",
    "timeSeriesGroupCorrectedUnreliable", "timeSeriesGroupFlagComparison",
    "timeSeriesGroupGeneral", "timeSeriesGroupHardMax",
    "timeSeriesGroupHardMin", "timeSeriesGroupMissing",
    "timeSeriesGroupOriginalDoubtful", "timeSeriesGroupOriginalReliable",
    "timeSeriesGroupOriginalUnreliable", "timeSeriesGroupOscillation",
    "timeSeriesGroupRateOfChange", "timeSeriesGroupSameReading",
    "timeSeriesGroupSeriesComparison", "timeSeriesGroupSoftMax",
    "timeSeriesGroupSoftMin", "timeSeriesGroupSpatialHomogeneity",
    "timeSeriesGroupTemporaryShift", "timeSeriesHydrograph",
    "timeSeriesHydrographModified", "timeSeriesListerConstantBackground",
    "timeSeriesListerWarningForeground", "timeSeriesSelectedBackground",
    "title", "titleBorderDisabled", "toolScrollBarUiBackEnd",
    "toolScrollBarUiBackStart", "toolTipBackground", "track",
    "trackForeground", "trackHighlight", "trackHighlightForeground",
    "valueAboveDetectionRangeBackground",
    "valueAutomaticallyCompletedBackground",
    "valueAutomaticallyCompletedForeground",
    "valueAutomaticallyCorrectedBackground",
    "valueAutomaticallyCorrectedForeground",
    "valueBelowDetectionRangeBackground", "valueDoubtfulBackground",
    "valueDriedBackground", "valueHasCommentMarkerBackground",
    "valueIceBackground", "valueInundatedBackground",
    "valueManualCompletedBackground", "valueManualCompletedForeground",
    "valueManualCorrectedBackground", "valueManualCorrectedForeground",
    "valueMissingBackground", "valueModifiedBackground",
    "valueNormalBackground", "valuePersistentUnreliableBackground",
    "valueAccumulationResetBackground", "valueSourceCyclicForeground",
    "valueUnmodifiedBackground", "valueUnreliableBackground",
    "waterCoachBorder", "window", "windowButtonBackgroundActiveEnd",
    "windowButtonBackgroundActiveStart", "windowButtonBackgroundInactive",
    "windowButtonForeground", "windowButtonForegroundUnavailable",
    "windowButtonMouseInBorder", "windowButtonMouseOutBorder",
    "windowTitleBarBackgroundActiveEnd",
    "windowTitleBarBackgroundActiveStart",
    "windowTitleBarBackgroundInactiveEnd",
    "windowTitleBarBackgroundInactiveStart",
    "windowTitleBarIdBackgroundActive", "windowTitleBarIdBackgroundAnimating",
    "windowTitleBarIdBackgroundFlashingOne",
    "windowTitleBarIdBackgroundFlashingZero",
    "windowTitleBarIdBackgroundGradientTop",
    "windowTitleBarIdBackgroundInactive", "windowTitleBarIdForegroundActive",
    "windowTitleBarIdForegroundInactive",
    "windowTitleBarTabForegroundSelected",
    "windowTitleBarTabForegroundUnselected", "zoomSelectionBackground",
)
