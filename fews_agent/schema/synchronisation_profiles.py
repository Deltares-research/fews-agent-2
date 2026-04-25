"""SynchronisationProfiles.xml — deprecated since 2017.02.

Root element is ``<profiles>``. Each profile bundles synchronisation
activities (channel + schedule choice + optional modifiers/triggers).

XSD inner choices:
- ``schedule``: single XOR continuous.
- ``modifier`` payload: synchLevel[] XOR logType[] XOR onlyActive.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import FewsModel, UnitMultiplier


SynchPriority = Literal["low", "normal", "high"]
LogType = Literal["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]


class SynchTrigger(FewsModel):
    activityId: str
    onlyForCurrentForecasts: bool
    useLastSynchTime: bool


class SynchTriggers(FewsModel):
    trigger: list[SynchTrigger] = Field(min_length=1)


class SynchModifier(FewsModel):
    """Inner XSD choice: synchLevel[] XOR logType[] XOR onlyActive."""

    tableId: str
    synchLevel: list[int] = Field(default_factory=list)
    logType: list[LogType] = Field(default_factory=list)
    onlyActive: bool | None = None
    downloadDataOnDemand: bool | None = None

    @model_validator(mode="after")
    def _one_filter(self) -> SynchModifier:
        variants = [
            bool(self.synchLevel),
            bool(self.logType),
            self.onlyActive is not None,
        ]
        if sum(variants) != 1:
            raise ValueError(
                "synchModifier: supply exactly one of synchLevel[] / logType[] / onlyActive"
            )
        return self


class SynchModifierList(FewsModel):
    modifier: list[SynchModifier] = Field(min_length=1)


class SynchModifiers(FewsModel):
    incoming: SynchModifierList | None = None
    outgoing: SynchModifierList | None = None


class SingleSynchActivity(FewsModel):
    priority: SynchPriority | None = None


class ContinuousSynchActivity(FewsModel):
    period: UnitMultiplier
    priority: SynchPriority | None = None


class SynchSchedule(FewsModel):
    """XSD choice: single XOR continuous (exactly one)."""

    single: SingleSynchActivity | None = None
    continuous: ContinuousSynchActivity | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> SynchSchedule:
        if (self.single is None) == (self.continuous is None):
            raise ValueError(
                "synchSchedule: supply exactly one of single or continuous"
            )
        return self


class SynchActivity(FewsModel):
    id: str
    channelId: str
    schedule: SynchSchedule
    timeOut: int
    optional: bool | None = None
    ignoreMaxSynchPeriod: bool | None = None
    overrulingMaxSynchPeriod: UnitMultiplier | None = None
    modifiers: SynchModifiers | None = None
    triggers: SynchTriggers | None = None


class SynchActivities(FewsModel):
    activity: list[SynchActivity] = Field(min_length=1)


class SynchProfile(FewsModel):
    id: str
    autoconnect: bool
    description: str | None = None
    customizable: bool | None = None
    maxSynchPeriod: UnitMultiplier | None = None
    activities: SynchActivities | None = None


class SynchronisationProfiles(FewsModel):
    defaultProfileId: str
    profile: list[SynchProfile] = Field(min_length=1)
