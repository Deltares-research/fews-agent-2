"""EventActions.xml — legacy event-action mappings (upload/download).

XSD carries both the legacy root (<eventActions> with LegacyEventAction
entries) and a non-root EventActionComplexType used by mc.xsd. We only
model the root form here.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel


class LegacyTag(FewsModel):
    name: str | None = None


class LegacyResume(FewsModel):
    """Empty — XSD LegacyResumeComplexType has no content."""


class LegacySuspend(FewsModel):
    """Empty — XSD LegacySuspendComplexType has no content."""


class LegacyRepeatInterval(FewsModel):
    interval: int | None = None


class LegacyEnhance(FewsModel):
    tag: LegacyTag
    resume: LegacyResume | None = None
    suspend: LegacySuspend | None = None
    repeatinterval: LegacyRepeatInterval | None = None

    @model_validator(mode="after")
    def _exactly_one_action(self) -> LegacyEnhance:
        kinds = [self.resume, self.suspend, self.repeatinterval]
        if sum(1 for k in kinds if k is not None) != 1:
            raise ValueError(
                "legacyEnhance: supply exactly one of resume / suspend / repeatinterval"
            )
        return self


class LegacyOneoffCardinalTime(FewsModel):
    interval: int | None = None
    reference: str | None = None
    unit: str | None = None


class LegacyOneoff(FewsModel):
    cardinaltime: LegacyOneoffCardinalTime
    tag: LegacyTag


class LegacyEventAction(FewsModel):
    """XSD choice: enhance OR oneoff."""

    actionConfigurationId: str
    description: str
    enhance: LegacyEnhance | None = None
    oneoff: LegacyOneoff | None = None

    @model_validator(mode="after")
    def _enhance_xor_oneoff(self) -> LegacyEventAction:
        if (self.enhance is None) == (self.oneoff is None):
            raise ValueError(
                "legacyEventAction: supply exactly one of enhance or oneoff"
            )
        return self


class EventActions(FewsModel):
    """Root of EventActions.xml."""

    eventAction: list[LegacyEventAction] = Field(default_factory=list)
