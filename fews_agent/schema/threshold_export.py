"""ThresholdExport.xml — threshold-crossing exporter (CAP-AU / CAP-EA).

Root element is ``<thresholdExport>`` with one or more ``<export>`` entries.
Each export filters threshold crossings by event-code patterns and filter
(locationSet + parameter) and renders them via a template file into CAP
XML files in a folder or posted to a server URL.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import (
    Addition,
    CalendarTimeSpan,
    FewsModel,
    RelativeViewPeriod,
    TimeZone,
)


ThresholdExportType = Literal["CAP-AU", "CAP-EA"]


class ThresholdExportFileName(FewsModel):
    name: str
    prefix: Addition | None = None
    suffix: Addition | None = None


class ThresholdExportDateFormat(FewsModel):
    id: str
    timeZone: TimeZone | None = None
    dateTimePattern: str


class ThresholdExportNumberFormat(FewsModel):
    id: str
    pattern: str


class ThresholdLogFilter(FewsModel):
    locationSetId: list[str] = Field(default_factory=list)
    parameterId: list[str] = Field(default_factory=list)


class MapThreshold(FewsModel):
    thresholdId: str
    value: str


class MultiValuedAttributeTag(FewsModel):
    tag: str
    upCrossingAttributeId: str
    downCrossingAttributeId: str


class ThresholdExport(FewsModel):
    """One ``<export>`` entry — server-upload section, matching-attribute
    section, and data-feed-status section are each optional XSD sub-
    groups with internal required-together fields."""

    exportTypeStandard: ThresholdExportType
    folder: str
    exportFileName: ThresholdExportFileName
    # optional <serverUrl ...><user ...>(password|encryptedPassword) group
    serverUrl: str | None = None
    connectionTimeOutMillis: int | None = None
    pauseMillis: int | None = None
    user: str | None = None
    password: str | None = None
    encryptedPassword: str | None = None
    relativeViewPeriod: RelativeViewPeriod | None = None
    eventCodePattern: list[str] = Field(min_length=1)
    templateFile: str
    dateFormat: list[ThresholdExportDateFormat] = Field(default_factory=list)
    numberFormat: list[ThresholdExportNumberFormat] = Field(default_factory=list)
    filter: ThresholdLogFilter | None = None
    thresholdHistorySearchTimeSpan: CalendarTimeSpan
    eventExpiryTime: CalendarTimeSpan
    identifier: str
    sender: str
    mapThreshold: list[MapThreshold] = Field(default_factory=list)
    # optional <matchingValueAttributeId>+<multiValuedAttributeTag>+ group
    matchingValueAttributeId: str | None = None
    multiValuedAttributeTag: list[MultiValuedAttributeTag] = Field(default_factory=list)
    # optional dataFeed-status choice
    dataFeedId: str | None = None
    disableDataFeedInfo: bool = False

    @model_validator(mode="after")
    def _cross_field_rules(self) -> ThresholdExport:
        # server-upload section: if any member is set, serverUrl + user +
        # exactly one of password/encryptedPassword must all be set.
        server_fields = [
            self.serverUrl,
            self.connectionTimeOutMillis,
            self.pauseMillis,
            self.user,
            self.password,
            self.encryptedPassword,
        ]
        if any(f is not None for f in server_fields):
            if self.serverUrl is None or self.user is None:
                raise ValueError(
                    "thresholdExport: serverUrl + user are required when any "
                    "server-upload field is set"
                )
            if (self.password is None) == (self.encryptedPassword is None):
                raise ValueError(
                    "thresholdExport: supply exactly one of password or "
                    "encryptedPassword"
                )
        # matching-attribute section: both or neither.
        if (self.matchingValueAttributeId is None) != (
            not self.multiValuedAttributeTag
        ):
            raise ValueError(
                "thresholdExport: matchingValueAttributeId requires at least "
                "one multiValuedAttributeTag (and vice versa)"
            )
        # dataFeed choice: at most one branch.
        if self.dataFeedId is not None and self.disableDataFeedInfo:
            raise ValueError(
                "thresholdExport: pick dataFeedId OR disableDataFeedInfo, not both"
            )
        return self


class ThresholdExportModule(FewsModel):
    """Root of ``<thresholdExport>``."""

    export: list[ThresholdExport] = Field(min_length=1)
