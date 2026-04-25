"""TimeSeriesDisplayConfig.xml — UI display defaults and color scales.

This is the biggest display config. Major blocks:

  - generalDisplayConfig / defaultViewPeriod — UI defaults
  - classBreaks (container)
      * inner classBreaks id=... — either:
          - discrete: list of <color color .../> entries
          - gradient: one or more GradientSegments, each a run of
            (lowerColor, upperColor, [lowerOpaquenessPercentage,
             upperOpaquenessPercentage], [lowerSymbolSize, upperSymbolSize],
             lowerValue*). Tutorial Class.Temperature has two segments
             (cold / hot) interleaved in the XML, so we model as an ordered
             list rather than flat lists.
  - timeMarkersDisplayConfig — per-marker color + lineStyle
  - parametersDisplayConfig — per-parameterId color/line/marker/range
  - statisticalFunctions — named functions with optional timeStep/timeSpan
  - descriptiveFunctionGroups — reused from modifier_types
  - defaultGraphicalEditMode — string enum
  - buttonSettings — 32 flag-like empty elements with optional `visible` attr
"""
from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from .common import FewsModel, RelativePeriod
from .enums import TimeUnit
from .ids import ClassBreaksId
from .modifier_types import DescriptiveFunctionGroups


class GeneralDisplayConfig(FewsModel):
    """Top-level UI defaults. legendTextFunction uses FEWS tokens
    like `%PARAMETER_NAME%`, passed through verbatim."""

    legendFontSize: int | None = None
    legendTextFunction: str | None = None
    showLocationInLegendWithSingleLocation: bool | None = None
    axisTitleFontSize: int | None = None
    tickLabelFontSize: int | None = None
    thresholdLabelFontSize: int | None = None
    barMarginPercentage: int | None = None
    toolTipMargin: int | None = None
    valueColumnWidth: int | None = None
    convertDatum: bool | None = None
    autoScaleForAllThresholds: bool | None = None
    onlyShowThresholdsSharedByAllSeries: bool | None = None
    unreliablesVisibleInChart: bool | None = None
    maximumInterpolationGap: int | None = None
    valueEditorPermission: str | None = None
    labelEditorPermission: str | None = None
    commentEditorPermission: str | None = None
    chainageUnit: str | None = None
    headerLine: list[str] = Field(default_factory=list)


class DefaultViewPeriod(FewsModel):
    """XSD RelativePeriodComplexType — start/end/unit, optional description
    and startOverrulable/endOverrulable attrs."""

    unit: TimeUnit
    start: int
    end: int
    startOverrulable: bool | None = None
    endOverrulable: bool | None = None
    description: str | None = None


class DiscreteColor(FewsModel):
    """One color step in discrete-color classBreaks.

    lowerValue is str — tutorial uses "0" for integer-valued breaks and
    Python float round-trip emits "0.0". Same preservation trick as
    elsewhere.
    """

    color: str
    lowerValue: str
    opaquenessPercentage: int | None = Field(default=None, ge=0, le=100)
    label: str | None = None


class GradientSegment(FewsModel):
    """One gradient run inside a classBreaks entry.

    Element order when rendered: lowerColor, upperColor,
    lowerOpaquenessPercentage, upperOpaquenessPercentage,
    lowerSymbolSize, upperSymbolSize, lowerValue*.
    """

    lowerColor: str
    upperColor: str
    lowerOpaquenessPercentage: int | None = None
    upperOpaquenessPercentage: int | None = None
    lowerSymbolSize: int | None = None
    upperSymbolSize: int | None = None
    # str for same source-preservation reason as DiscreteColor.lowerValue.
    lowerValue: list[str] = Field(default_factory=list)


class ClassBreaksEntry(FewsModel):
    """One named color scale, either discrete or gradient (possibly
    multi-segment). At least one of `color` or `segment` must be set."""

    id: ClassBreaksId
    color: list[DiscreteColor] = Field(default_factory=list)
    segment: list[GradientSegment] = Field(default_factory=list)

    @model_validator(mode="after")
    def _has_some_content(self) -> ClassBreaksEntry:
        if not self.color and not self.segment:
            raise ValueError(
                f"classBreaks '{self.id}': supply either discrete colors or gradient segments"
            )
        return self


class ClassBreaks(FewsModel):
    """Container wrapping one or more named classBreaks entries."""

    classBreaks: list[ClassBreaksEntry] = Field(min_length=1)


# ---------------------------------------------------------------------------
# timeMarkersDisplayConfig
# ---------------------------------------------------------------------------

class TimeMarkerDisplayOptions(FewsModel):
    marker: str
    color: str
    lineStyle: str
    label: str | None = None


class TimeMarkersDisplayConfig(FewsModel):
    description: str | None = None
    timeMarkerDisplayOptions: list[TimeMarkerDisplayOptions] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# parametersDisplayConfig
# ---------------------------------------------------------------------------

class ParameterDisplayOptions(FewsModel):
    # Attrs
    id: str
    name: str | None = None
    equidistant: bool | None = None
    # Elements
    qualifierId: list[str] = Field(default_factory=list)
    ensembleId: list[str] = Field(default_factory=list)
    ensembleMemberIndex: list[str] = Field(default_factory=list)
    preferredColor: str | None = None
    lineStyle: str | None = None
    markerStyle: str | None = None
    markerSize: int | None = None
    # min/max: str to preserve "0"/"2" integer form (float → "0.0"/"2.0").
    min: str | None = None
    max: str | None = None
    inverted: bool | None = None


class ParametersDisplayConfig(FewsModel):
    description: str | None = None
    defaults: dict[str, Any] | None = None
    parameterDisplayOptions: list[ParameterDisplayOptions] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# statisticalFunctions
# ---------------------------------------------------------------------------

class StatisticalFunctionTimeStep(FewsModel):
    """TimeStepComplexType — full XSD coverage."""

    id: str | None = None
    unit: str | None = None
    multiplier: int | str | None = None
    divider: int | str | None = None
    label: str | None = None
    times: str | None = None
    minutes: str | None = None
    daysOfMonth: str | None = None
    monthDays: str | None = None
    timeZone: str | None = None
    description: str | None = None


class StatisticalFunctionTimeSpan(FewsModel):
    unit: TimeUnit
    multiplier: int | None = None
    divider: int | None = None


class StatisticalFunction(FewsModel):
    # Attrs
    id: str | None = None
    function: str
    label: str | None = None
    ignoreMissings: bool | None = None
    aggregateByParameterType: str | None = None
    # Elements in XSD sequence order
    timeStep: list[StatisticalFunctionTimeStep] = Field(default_factory=list)
    movingAccumulationTimeSpan: list[StatisticalFunctionTimeSpan] = Field(
        default_factory=list
    )
    annotationTimeSpan: dict[str, Any] | None = None
    parameterId: str | None = None
    simulatedParameterId: str | None = None
    observedParameterId: str | None = None
    allowedInputParameterId: list[str] = Field(default_factory=list)
    lineStyle: str | None = None
    historicalPeriods: dict[str, Any] | None = None
    maxEstimatedValue: str | None = None
    samples: dict[str, Any] | None = None
    season: list[dict[str, Any]] = Field(default_factory=list)
    statisticType: str | None = None
    areaFunction: dict[str, Any] | None = None
    dateFormat: str | None = None


class StatisticalFunctions(FewsModel):
    statisticalFunction: list[StatisticalFunction] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# buttonSettings
# ---------------------------------------------------------------------------

class ButtonFlag(FewsModel):
    """Button-enable flag (XSD ButtonSettingComplexType).

    Element presence means the button is enabled. Optional attributes:

      - ``visible`` — hide/show the button in the UI (default true).
      - ``permission`` — restrict visibility to users with the named
        permission (default: empty, i.e. visible to all).
      - ``selected`` — pre-select the button at startup (default false;
        only meaningful for `showThresholdWarningLevels` and
        `switchReferenceLevel`).
    """

    visible: bool | None = None
    permission: str | None = None
    selected: bool | None = None


class ThresholdGroupSelectionButton(FewsModel):
    """ThresholdGroupSelectionButtonComplexType — visible attr (required)
    + optional defaultThresholdGroupId child element."""

    visible: bool
    defaultThresholdGroupId: str | None = None


class SearchAndSelectForecastButton(ButtonFlag):
    """SearchAndSelectForecastButtonSettingComplexType — extends
    ButtonSettingComplexType with the relative search period."""

    forecastSearchPeriod: RelativePeriod | None = None


class ButtonSettings(FewsModel):
    """Every button flag FEWS knows about. Fields declared in tutorial
    order — C14N preserves element order so Pydantic field declaration
    order matters at emission time."""

    showDisplayGroups: ButtonFlag | None = None
    showTable: ButtonFlag | None = None
    showTwentyFourHour: ButtonFlag | None = None
    showChart: ButtonFlag | None = None
    showStatistics: ButtonFlag | None = None
    rotateChartAndTable: ButtonFlag | None = None
    zoomIn: ButtonFlag | None = None
    zoomOut: ButtonFlag | None = None
    zoomToDefault: ButtonFlag | None = None
    selectPreviousZoomLevel: ButtonFlag | None = None
    selectNextZoomLevel: ButtonFlag | None = None
    moveBackOneViewPeriod: ButtonFlag | None = None
    moveBackHalfViewPeriod: ButtonFlag | None = None
    moveForwardHalfViewPeriod: ButtonFlag | None = None
    moveForwardOneViewPeriod: ButtonFlag | None = None
    showAllData: ButtonFlag | None = None
    switchReferenceLevel: ButtonFlag | None = None
    setViewPeriod: ButtonFlag | None = None
    copyTimeSeries: ButtonFlag | None = None
    pasteTimeSeries: ButtonFlag | None = None
    lockSelection: ButtonFlag | None = None
    runWorkflow: ButtonFlag | None = None
    undoTimeSeriesChanges: ButtonFlag | None = None
    saveTimeSeriesChanges: ButtonFlag | None = None
    setTimeSeriesEditableByClicking: ButtonFlag | None = None
    showThresholdWarningLevels: ButtonFlag | None = None
    printChart: ButtonFlag | None = None
    saveChartAsPicture: ButtonFlag | None = None
    showLongTermScroller: ButtonFlag | None = None
    searchAndSelectForecasts: SearchAndSelectForecastButton | None = None
    setTimeSeriesVisibility: ButtonFlag | None = None
    showValidationRules: ButtonFlag | None = None
    # --- XSD-complete tail (added in gap-close pass) ---
    showValidationColumn: ButtonFlag | None = None
    showValidationStepsColumn: ButtonFlag | None = None
    showUsersColumn: ButtonFlag | None = None
    showCommentsColumn: ButtonFlag | None = None
    showUnitsColumn: ButtonFlag | None = None
    showLocationNamesInTableHeader: ButtonFlag | None = None
    showLocationIdsInTableHeader: ButtonFlag | None = None
    showModuleInstanceInTableHeader: ButtonFlag | None = None
    showForecastTimesInTableHeader: ButtonFlag | None = None
    showColumnStatistics: ButtonFlag | None = None
    showThresholdCrossings: ButtonFlag | None = None
    twentyFourHourOptions: ButtonFlag | None = None
    groupTableByTimeSeries: ButtonFlag | None = None
    reverseTimeSeriesOrder: ButtonFlag | None = None
    toggleGraphSplitting: ButtonFlag | None = None
    toggleGraphEqualScale: ButtonFlag | None = None
    scaleToShowUnreliableData: ButtonFlag | None = None
    showDataLabels: ButtonFlag | None = None
    switchFilterAndShortcuts: ButtonFlag | None = None
    hideUnreliableData: ButtonFlag | None = None
    stackPlot: ButtonFlag | None = None
    legendDisplayOptions: ButtonFlag | None = None
    hideFooter: ButtonFlag | None = None
    thresholdDisplayOptions: ButtonFlag | None = None
    useColorMap: ButtonFlag | None = None
    toggleValidationInChart: ButtonFlag | None = None
    toggleUsersInChart: ButtonFlag | None = None
    toggleCommentsInChart: ButtonFlag | None = None
    toggleProductInfoInChart: ButtonFlag | None = None
    toggleLongitudinalProfileMarkers: ButtonFlag | None = None
    showInteractionScatterPlot: ButtonFlag | None = None
    showLookupTable: ButtonFlag | None = None
    moveToFirstDataPoint: ButtonFlag | None = None
    moveToLastDataPoint: ButtonFlag | None = None
    activateModify: ButtonFlag | None = None
    useGraphicalEditorMovePointMode: ButtonFlag | None = None
    useSetToMissingBetweenSelectedPointsMode: ButtonFlag | None = None
    useInterpolateBetweenSelectedPointsMode: ButtonFlag | None = None
    useGraphicalEditorQuadraticInterpolationMode: ButtonFlag | None = None
    useGraphicalEditorVerticalMoveMode: ButtonFlag | None = None
    useNoGraphicalEditMode: ButtonFlag | None = None
    selectPoints: ButtonFlag | None = None
    deselectPoints: ButtonFlag | None = None
    selectOrDeselectPoint: ButtonFlag | None = None
    selectPointsByDrawingRectangle: ButtonFlag | None = None
    moveSelectedPointsVerticallyByDragging: ButtonFlag | None = None
    markPeriod: ButtonFlag | None = None
    unmarkPeriod: ButtonFlag | None = None
    openManualEditor: ButtonFlag | None = None
    moveHighLightedTimeStepToLeft: ButtonFlag | None = None
    moveHighLightedTimeStepToRight: ButtonFlag | None = None
    moveTimeCursorToLeft: ButtonFlag | None = None
    moveTimeCursorToRight: ButtonFlag | None = None
    increaseValue: ButtonFlag | None = None
    decreaseValue: ButtonFlag | None = None
    undoEdit: ButtonFlag | None = None
    cancelEdit: ButtonFlag | None = None
    thresholdGroupSelectionButton: ThresholdGroupSelectionButton | None = None
    setTimeSeriesResampling: ButtonFlag | None = None
    hideEmptyTimeSeries: ButtonFlag | None = None
    showTimeSeriesLister: ButtonFlag | None = None
    showHistoricalAnalysis: ButtonFlag | None = None


# ---------------------------------------------------------------------------
# root
# ---------------------------------------------------------------------------

class TimeSeriesDisplay(FewsModel):
    """Root of TimeSeriesDisplayConfig.xml.

    Many optional sub-blocks are accepted as ``dict[str, Any]``
    passthroughs rendered via ``dict_to_xml`` — display configuration
    tends to have deep, rarely-authored sub-trees (ToolTipsConfig,
    LegendDisplayOptions, ThresholdDisplayConfig, etc.). Common blocks
    stay fully typed.
    """

    description: str | None = None
    generalDisplayConfig: GeneralDisplayConfig | None = None
    defaultViewPeriod: DefaultViewPeriod | None = None
    globalDatumLocationSetId: str | None = None
    scrollerDefaultViewPeriod: RelativePeriod | None = None
    showAllScrollerData: bool | None = None
    showAllSubPlotInScroller: bool | None = None
    readOnlyPeriod: list[dict[str, Any]] = Field(default_factory=list)
    timeOfValidityDefaultViewPeriod: RelativePeriod | None = None
    timeOfValiditySearchPeriod: RelativePeriod | None = None
    thresholdDisplayConfig: dict[str, Any] | None = None
    toolTipsConfig: dict[str, Any] | None = None
    legend: dict[str, Any] | None = None
    showValueInLegend: bool | None = None
    showTimeStepInLegend: bool | None = None
    hideFooter: bool | None = None
    classBreaks: ClassBreaks | None = None
    timeMarkersDisplayConfig: TimeMarkersDisplayConfig | None = None
    defaultColorList: dict[str, Any] | None = None
    tableBackgroundColors: dict[str, Any] | None = None
    highlightedDateTickColor: str | None = None
    ratingCurveDisplayConfig: dict[str, Any] | None = None
    parametersDisplayConfig: ParametersDisplayConfig | None = None
    moduleInstanceIdMappings: dict[str, Any] | None = None
    sampleFunctions: dict[str, Any] | None = None
    statisticalFunctions: StatisticalFunctions | None = None
    quickViewStatisticalFunction: dict[str, Any] | None = None
    combinedTimeSeriesStatisticalFunctions: dict[str, Any] | None = None
    descriptiveFunctionGroups: DescriptiveFunctionGroups | None = None
    tickUnitsConfig: dict[str, Any] | None = None
    defaultGraphicalEditMode: str | None = None
    graphicalEditingConfig: dict[str, Any] | None = None
    thresholdGroupSelectionButton: dict[str, Any] | None = None
    buttonSettings: ButtonSettings | None = None
    predefinedViewPeriods: dict[str, Any] | None = None
    invertTableOrder: bool | None = None
    showDisplayGroupsHideAllToolWindows: dict[str, Any] | None = None
    resampling: dict[str, Any] | None = None
    infoAttribute: dict[str, Any] | None = None
    documentViewer: dict[str, Any] | None = None
    version: str = "1.0"
