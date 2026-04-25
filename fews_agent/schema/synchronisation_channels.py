"""SynchronisationChannels.xml — deprecated since 2017.02.

Flat list of ``<channel id="...">`` entries each holding incoming and
outgoing sets of database table names.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class SynchChannelTableNames(FewsModel):
    table: list[str] = Field(default_factory=list)


class SynchChannel(FewsModel):
    id: str
    incoming: SynchChannelTableNames
    outgoing: SynchChannelTableNames
    description: str | None = None


class SynchronisationChannels(FewsModel):
    channel: list[SynchChannel] = Field(min_length=1)
