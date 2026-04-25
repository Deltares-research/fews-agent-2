"""PerformanceIndicatorSets.xml — forecast-vs-observed performance indicators.

Each ``<performanceIndicatorSet>`` has input/output variables and a
choice of one indicator kind (XSD xs:choice maxOccurs=unbounded):

  - modulePerformanceIndicator
  - leadTimeAccuracyIndicator
  - thresholdTimingIndicator
  - precipitationPerformanceIndicator
  - peaksAccuracyIndicator

As with ``massBalance`` / ``whatIfTemplates``, the choice is modelled as
parallel lists and emitted in a fixed order.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import (
    CalendarTimeSpan,
    DataVariable,
    FewsModel,
    RelativeViewPeriod,
)


LogLevel = Literal["DEBUG", "INFO", "WARN", "ERROR", "FATAL"]

ModulePerformance = Literal[
    "bias", "meanabsoluteerror", "meansquareerror", "nashsutcliffeefficiency",
    "peakmeansquareerror", "volumeerror", "MAE", "MSE", "NSE", "PeakMSE",
    "PercVol", "RMSE", "RMSF", "CorrelationCoeffient", "R2",
    "OverPredictionRate", "UnderPredictionRate", "standarddeviation",
]
LeadTimeAccuracy = Literal[
    "bias", "meanabsoluteerror", "meansquareerror", "MAE", "MSE", "RMSE",
    "RMSF", "CorrelationCoeffient", "R2", "OverPredictionRate",
    "UnderPredictionRate", "BrierScore", "RPS", "RankedProbabilityScore",
    "standarddeviation",
]
PeakAccuracy = Literal[
    "bias", "meanabsoluteerror", "meansquareerror", "MAE", "MSE", "RMSE",
    "RMSF", "CorrelationCoeffient", "R2", "standarddeviation",
]
ThresholdTimingAccuracy = Literal["bias", "meanabsoluteerror", "MAE"]
PrecipitationPerformance = Literal["bias", "RMSE", "RMSF"]
Criteria = Literal[
    "minnumberofforecasts", "timewindowinseconds", "timeshiftwindowinseconds",
    "thresholdvaluesetid", "peakthresholdvalue",
    "maximumgapbetweenpeaksinseconds", "minimumrecessionbetweenpeaks",
    "minimumValue",
]


class CriteriaEntry(FewsModel):
    criteria: Criteria
    value: str
    violationOfCriteriaFaggedAs: str | None = None  # XSD attr is spelled this way
    description: str | None = None


class ModulePerformanceIndicator(FewsModel):
    indicatorType: ModulePerformance
    calculatedVariableId: str
    observedVariableId: str
    outputVariableId: str
    sampleOutputVariableId: str | None = None
    analysedCalculatedVariableId: str | None = None
    analysedObservedVariableId: str | None = None
    additionalCriteria: list[CriteriaEntry] = Field(default_factory=list)


class LeadTime(FewsModel):
    time: int
    outputVariableId: str | None = None


class LeadTimes(FewsModel):
    unit: str
    leadTime: list[LeadTime] = Field(min_length=1)
    divider: int | None = None
    multiplier: int | None = None


class LeadTimePeriod(FewsModel):
    start: int
    end: int
    outputVariableId: str | None = None
    sampleOutputVariableId: str | None = None


class LeadTimePeriods(FewsModel):
    unit: str
    leadTimePeriod: list[LeadTimePeriod] = Field(min_length=1)
    divider: int | None = None
    multiplier: int | None = None


class ThresholdClassBreaks(FewsModel):
    """XSD choice: thresholdId[] XOR classValue[]."""

    thresholdId: list[int] = Field(default_factory=list)
    classValue: list[float] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_form(self) -> ThresholdClassBreaks:
        has_ids = bool(self.thresholdId)
        has_vals = bool(self.classValue)
        if has_ids == has_vals:
            raise ValueError(
                "classBreaks: supply exactly one of thresholdId or classValue"
            )
        return self


class LeadTimeAccuracyIndicator(FewsModel):
    """Choice: leadTimes XOR leadTimePeriods."""

    indicatorType: LeadTimeAccuracy
    calculatedVariableId: str
    observedVariableId: str
    additionalCriteria: list[CriteriaEntry] = Field(default_factory=list)
    classBreaks: ThresholdClassBreaks | None = None
    leadTimes: LeadTimes | None = None
    leadTimePeriods: LeadTimePeriods | None = None
    outputVariableId: str | None = None
    sampleOutputVariableId: str | None = None
    intermediateValuesVariableId: str | None = None
    analysedCalculatedVariableId: str | None = None
    analysedObservedVariableId: str | None = None

    @model_validator(mode="after")
    def _one_leads(self) -> LeadTimeAccuracyIndicator:
        if (self.leadTimes is None) == (self.leadTimePeriods is None):
            raise ValueError(
                "leadTimeAccuracyIndicator: supply exactly one of leadTimes or "
                "leadTimePeriods"
            )
        return self


class ThresholdIdEntry(FewsModel):
    intId: int
    outputVariableId: str | None = None


class ThresholdIds(FewsModel):
    thresholdId: list[ThresholdIdEntry] = Field(min_length=1)


class ThresholdTimingIndicator(FewsModel):
    indicatorType: ThresholdTimingAccuracy
    calculatedVariableId: str
    observedVariableId: str
    additionalCriteria: list[CriteriaEntry] = Field(default_factory=list)
    thresholdIds: ThresholdIds


class PrecipitationPerformanceIndicator(FewsModel):
    indicatorType: PrecipitationPerformance
    observedVariableId: str
    forecastVariableId: str
    outputVariableId: str
    accumulationPeriod: RelativeViewPeriod
    assessmentInterval: CalendarTimeSpan
    additionalCriteria: list[CriteriaEntry] = Field(default_factory=list)


class SelectPeak(FewsModel):
    peak: int
    outputVariableId: str | None = None


class SelectPeaks(FewsModel):
    selectPeak: list[SelectPeak] = Field(min_length=1)


class PeaksAccuracyIndicator(FewsModel):
    indicatorType: PeakAccuracy
    calculatedVariableId: str
    observedVariableId: str
    referenceVariableId: str
    selectPeaks: SelectPeaks
    outputVariableId: str | None = None
    additionalCriteria: list[CriteriaEntry] = Field(default_factory=list)


class PerformanceIndicatorSet(FewsModel):
    """Models the XSD's two choices as parallel optional/list fields.

    The outer 'period selection' choice (``forecastSelectionPeriod`` XOR
    ``observedSelectionPeriod``) is enforced by a validator. The inner
    indicator-kind choice is a parallel-list bag (any mix of kinds is
    schema-valid)."""

    performanceIndicatorId: str | None = None
    inputVariable: list[DataVariable] = Field(min_length=1)
    forecastSelectionPeriod: RelativeViewPeriod | None = None
    observedSelectionPeriod: RelativeViewPeriod | None = None
    modulePerformanceIndicator: list[ModulePerformanceIndicator] = Field(default_factory=list)
    leadTimeAccuracyIndicator: list[LeadTimeAccuracyIndicator] = Field(default_factory=list)
    thresholdTimingIndicator: list[ThresholdTimingIndicator] = Field(default_factory=list)
    precipitationPerformanceIndicator: list[PrecipitationPerformanceIndicator] = Field(default_factory=list)
    peaksAccuracyIndicator: list[PeaksAccuracyIndicator] = Field(default_factory=list)
    outputVariable: list[DataVariable] = Field(min_length=1)

    @model_validator(mode="after")
    def _period_choice_and_indicator(self) -> PerformanceIndicatorSet:
        if (
            self.forecastSelectionPeriod is not None
            and self.observedSelectionPeriod is not None
        ):
            raise ValueError(
                "performanceIndicatorSet: supply at most one of "
                "forecastSelectionPeriod or observedSelectionPeriod"
            )
        if not any(
            [
                self.modulePerformanceIndicator,
                self.leadTimeAccuracyIndicator,
                self.thresholdTimingIndicator,
                self.precipitationPerformanceIndicator,
                self.peaksAccuracyIndicator,
            ]
        ):
            raise ValueError(
                "performanceIndicatorSet: supply at least one indicator entry"
            )
        return self


class PerformanceIndicatorSets(FewsModel):
    version: str = "1.1"
    debugLevel: int = 0
    logLevel: LogLevel | None = None
    performanceIndicatorSet: list[PerformanceIndicatorSet] = Field(min_length=1)
