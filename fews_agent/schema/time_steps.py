"""TimeSteps.xml — registry of named timeStep ids.

Four variants at the root level:
  - ``timeStep`` — the standard NamedTimeStep shape (unit+multiplier /
    times / daysOfMonth / monthDays).
  - ``weeklyTimeStep`` — per-weekday times pattern (Mon/Tue/.../Sun).
  - ``monthlyTimeStep`` — up to 6 days-of-month with aggregation periods.
  - ``yearlyTimeStep`` — up to 4 month-day points per year (seasons).
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel
from .enums import TimeUnit


class NamedTimeStep(FewsModel):
    id: str
    unit: TimeUnit | None = None
    multiplier: int | str | None = None
    times: str | None = None  # space-separated "HH:MM" list
    timeZone: str | None = None


class TimesOfWeekDay(FewsModel):
    """``times`` is a space-separated list of HH:MM times, e.g. ``06:00 18:00``."""

    times: str


class WeeklyTimeStep(FewsModel):
    """One weekly pattern — each weekday is optional; omitting a day
    excludes it from the pattern."""

    id: str
    timeZone: str | None = None
    label: str | None = None
    sunday: TimesOfWeekDay | None = None
    monday: TimesOfWeekDay | None = None
    tuesday: TimesOfWeekDay | None = None
    wednesday: TimesOfWeekDay | None = None
    thursday: TimesOfWeekDay | None = None
    friday: TimesOfWeekDay | None = None
    saturday: TimesOfWeekDay | None = None


class DayOfMonthWithAggregationPeriod(FewsModel):
    """Value day + aggregation window (start exclusive, end inclusive).
    All three are day-of-month list strings (``daysOfMonthListType``)."""

    value: str
    start: str
    end: str


class MonthlyTimeStep(FewsModel):
    """At most 6 days-of-month entries per month."""

    id: str
    day: list[DayOfMonthWithAggregationPeriod] = Field(min_length=1, max_length=6)
    timeZone: str | None = None
    label: str | None = None


class MonthDayWithAggregationPeriod(FewsModel):
    """Value month-day + aggregation season (start exclusive, end
    inclusive). Each is a ``--MM-DD`` gMonthDay string."""

    value: str
    start: str
    end: str


class YearlyTimeStep(FewsModel):
    """At most 4 month-day points per year (meant for seasons)."""

    id: str
    monthDay: list[MonthDayWithAggregationPeriod] = Field(min_length=1, max_length=4)
    timeZone: str | None = None
    label: str | None = None


class TimeSteps(FewsModel):
    """Root of TimeSteps.xml. At least one entry of any kind is required
    by the XSD (``choice maxOccurs=unbounded``)."""

    timeStep: list[NamedTimeStep] = Field(default_factory=list)
    weeklyTimeStep: list[WeeklyTimeStep] = Field(default_factory=list)
    monthlyTimeStep: list[MonthlyTimeStep] = Field(default_factory=list)
    yearlyTimeStep: list[YearlyTimeStep] = Field(default_factory=list)
