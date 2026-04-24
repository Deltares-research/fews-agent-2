"""ErrorModelSets.xml — ARMA-style error-correction models.

Each ``<errorModelSet>`` binds input variables to an output variable
via a correction method (auto-order ARMA vs fixed-order ARMA), with
optional interpolation / clipping / doubtful-handling / log-level
parameters.

Attribute-and-property typed elements (booleanString… /
intString… / floatString…) accept either a typed value or a
``@ATTRIBUTE_ID@`` reference — modelled as plain ``str`` throughout
to round-trip both forms unchanged.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import DataVariable, FewsModel, RelativeViewPeriod


LogLevel = Literal["error", "warn", "info", "debug"]
CorrectionModel = Literal[
    "none", "ARMA + systematic", "systematic", "ARMA",
    "ARMA + log transformation", "ARMA + systematic + log transformation",
]
InterpolationType = Literal["defaultvalue", "linear", "block"]
ParameterType = Literal["ar", "ma"]


class ErrorModelParameter(FewsModel):
    """simpleContent extension: numeric float body + ``type`` / ``order`` attrs."""

    value: str  # floatStringAttributeAndPropertyType — keep as string
    type: ParameterType
    order: int = Field(ge=1)


class ErrorModelParameters(FewsModel):
    parameter: list[ErrorModelParameter] = Field(min_length=1)


class AutoOrderMethod(FewsModel):
    orderSelection: str  # booleanStringAttributeAndPropertyType
    observedTimeSeriesId: str
    simulatedTimeSeriesId: list[str] = Field(min_length=1)
    outputTimeSeriesId: str
    subtractMean: str  # booleanStringAttributeAndPropertyType
    boxcoxTransformation: str  # booleanStringAttributeAndPropertyType
    order_ar: str | None = None  # intStringAttributeAndPropertyType
    order_ma: str | None = None
    parameters: ErrorModelParameters | None = None
    lambda_: str | None = Field(default=None, alias="lambda")
    analysisWindow: RelativeViewPeriod | None = None


class FixedOrderMethod(FewsModel):
    correctionModel: CorrectionModel
    observedTimeSeriesId: str
    simulatedTimeSeriesId: list[str] = Field(min_length=1)
    order_ar: str | None = None
    order_ma: str | None = None
    outputTimeSeriesId: str | None = None


class ErrorModelInterpolation(FewsModel):
    interpolationType: InterpolationType
    gapLength: int | None = None
    defaultValue: float | None = None


class ErrorModelSet(FewsModel):
    """XSD choice: autoOrderMethod XOR fixedOrderMethod."""

    inputVariable: list[DataVariable] = Field(min_length=1)
    outputVariable: DataVariable
    autoOrderMethod: AutoOrderMethod | None = None
    fixedOrderMethod: FixedOrderMethod | None = None
    interpolationOptions: ErrorModelInterpolation | None = None
    maxObserved: float | None = None
    minObserved: float | None = None
    maxResult: float | None = None
    minResult: float | None = None
    ignoreDoubtful: bool | None = None
    ignoreTrailingMissingsInSimulatedTimeSeries: bool | None = None
    loopOverMultipleTimeSeries: bool | None = None
    logLevelNoObservedValues: LogLevel | None = None

    @model_validator(mode="after")
    def _one_method(self) -> ErrorModelSet:
        if (self.autoOrderMethod is None) == (self.fixedOrderMethod is None):
            raise ValueError(
                "errorModelSet: supply exactly one of autoOrderMethod or "
                "fixedOrderMethod"
            )
        return self


class ErrorModelSets(FewsModel):
    version: str = "1.1"
    errorModelSet: list[ErrorModelSet] = Field(min_length=1)
    logLevelCoefficientsInfo: LogLevel | None = None
