"""FEWS enumerated value types.

`StrEnum` (Python 3.11+) gives named members while still being a `str`
subclass — so Pydantic validation, JSON serialization, and Jinja rendering
all emit the raw FEWS-defined string value with no `.value` accessor.

When the XSD pins a stricter set (or extends one), update here and link the
XSD fragment in a comment above the class.
"""
from enum import StrEnum


class ValueType(StrEnum):
    GRID = "grid"
    SCALAR = "scalar"


class TimeSeriesType(StrEnum):
    EXTERNAL_HISTORICAL = "external historical"
    EXTERNAL_FORECASTING = "external forecasting"
    SIMULATED_HISTORICAL = "simulated historical"
    SIMULATED_FORECASTING = "simulated forecasting"


class ReadWriteMode(StrEnum):
    ADD_ORIGINALS = "add originals"
    OVERWRITE_EXISTING = "overwrite existing values"
    READ_ONLY = "read only"
    READ_COMPLETE_FORECAST = "read complete forecast"
    READ_FIRST_VALUE_FOR_PREVIOUS_STEP = "read first value for previous step"


class ParameterType(StrEnum):
    INSTANTANEOUS = "instantaneous"
    ACCUMULATIVE = "accumulative"
    MEAN = "mean"


class TimeUnit(StrEnum):
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
    NONEQUIDISTANT = "nonequidistant"


class DefaultTimeAnchor(StrEnum):
    TIME_ZERO = "time zero"
    START_RUN = "start run"
    END_RUN = "end run"
    START_OF_FORECAST = "start of forecast"
    END_OF_FORECAST = "end of forecast"


class ModuleParameterValueType(StrEnum):
    BOOL = "boolValue"
    STRING = "stringValue"
    DOUBLE = "doubleValue"
    INT = "intValue"


class ExportActivityType(StrEnum):
    STATE = "exportStateActivity"
    DATASET = "exportDataSetActivity"
    PARAMETER = "exportParameterActivity"
    TIMESERIES = "exportTimeSeriesActivity"


class StateSelection(StrEnum):
    COLD_STATE = "coldState"
    WARM_STATE = "warmState"
    FROM_TIMESERIES = "fromTimeSeries"


# Preprocess / DataProcessing transformation kinds observed in tutorial.
# Not exhaustive — real XSD includes many more.
class TransformationKind(StrEnum):
    INTERPOLATION_SPATIAL = "interpolationSpatial"
    AGGREGATION_TEMPORAL = "aggregationTemporal"
    DISAGGREGATION_TEMPORAL = "disaggregationTemporal"
    MERGE = "merge"
    MODIFIER = "modifier"
    ENSEMBLE_STATISTICS_CALCULATOR = "ensembleStatisticsCalculator"
