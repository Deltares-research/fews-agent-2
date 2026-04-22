"""TimeSteps.xml — registry of named timeStep ids.

Each `<timeStep>` is one of two shapes:
  - interval: `unit` + `timeZone`  (daily, weekly, monthly, $DAY_TIMESTEP$)
  - discrete: `times="00:00 03:00 ..."` + `timeZone`  (GMT_3hourly)

Both forms always have an `id` attribute — it's the declaration everything
else references via `<timeStep id="..."/>`.
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


class TimeSteps(FewsModel):
    timeStep: list[NamedTimeStep] = Field(min_length=1)
