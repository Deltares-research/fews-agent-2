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

from pydantic import Field, model_validator

from .common import FewsModel
from .enums import TimeUnit
from .ids import ClassBreaksId
from .modifier_types import DescriptiveFunctionGroups


class GeneralDisplayConfig(FewsModel):
    """Top-level UI defaults. legendTextFunction uses FEWS tokens
    like `%PARAMETER_NAME%`, passed through verbatim."""

    legendTextFunction: str | None = None


class DefaultViewPeriod(FewsModel):
    unit: TimeUnit
    start: int
    end: int


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


class TimeMarkersDisplayConfig(FewsModel):
    timeMarkerDisplayOptions: list[TimeMarkerDisplayOptions] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# parametersDisplayConfig
# ---------------------------------------------------------------------------

class ParameterDisplayOptions(FewsModel):
    id: str
    preferredColor: str | None = None
    lineStyle: str | None = None
    markerStyle: str | None = None
    markerSize: int | None = None
    # min/max: str to preserve "0"/"2" integer form (float → "0.0"/"2.0").
    min: str | None = None
    max: str | None = None
    inverted: bool | None = None


class ParametersDisplayConfig(FewsModel):
    parameterDisplayOptions: list[ParameterDisplayOptions] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# statisticalFunctions
# ---------------------------------------------------------------------------

class StatisticalFunctionTimeStep(FewsModel):
    id: str


class StatisticalFunctionTimeSpan(FewsModel):
    unit: TimeUnit
    multiplier: int


class StatisticalFunction(FewsModel):
    function: str
    ignoreMissings: bool | None = None
    lineStyle: str | None = None
    timeStep: list[StatisticalFunctionTimeStep] = Field(default_factory=list)
    movingAccumulationTimeSpan: list[StatisticalFunctionTimeSpan] = Field(
        default_factory=list
    )


class StatisticalFunctions(FewsModel):
    statisticalFunction: list[StatisticalFunction] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# buttonSettings
# ---------------------------------------------------------------------------

class ButtonFlag(FewsModel):
    """Button-enable flag. Element presence means the button is enabled;
    optional `visible` attribute hides/shows it in the UI."""

    visible: bool | None = None


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
    searchAndSelectForecasts: ButtonFlag | None = None
    setTimeSeriesVisibility: ButtonFlag | None = None
    showValidationRules: ButtonFlag | None = None


# ---------------------------------------------------------------------------
# root
# ---------------------------------------------------------------------------

class TimeSeriesDisplay(FewsModel):
    """Root of TimeSeriesDisplayConfig.xml."""

    generalDisplayConfig: GeneralDisplayConfig | None = None
    defaultViewPeriod: DefaultViewPeriod | None = None
    classBreaks: ClassBreaks | None = None
    timeMarkersDisplayConfig: TimeMarkersDisplayConfig | None = None
    parametersDisplayConfig: ParametersDisplayConfig | None = None
    statisticalFunctions: StatisticalFunctions | None = None
    descriptiveFunctionGroups: DescriptiveFunctionGroups | None = None
    defaultGraphicalEditMode: str | None = None
    buttonSettings: ButtonSettings | None = None
    version: str = "1.0"
