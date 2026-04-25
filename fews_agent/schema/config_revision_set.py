"""ConfigRevisionSet.xml — single non-incremental config revision with
per-table entry lists. Note the root element is singular configRevisionSet."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class ConfigRevisionSetMetaData(FewsModel):
    revisionId: str
    numberOfChanges: int
    creationTime: str  # XSD dateTime — pass through as ISO string.
    creationUserId: str
    commentText: str | None = None


class ConfigRevisionSetTableVersion(FewsModel):
    table: str
    version: str
    entry: list[str] = Field(default_factory=list)


class ConfigRevisionSet(FewsModel):
    """Root of ConfigRevisionSet.xml (singular)."""

    metaData: ConfigRevisionSetMetaData
    tableVersion: list[ConfigRevisionSetTableVersion] = Field(default_factory=list)
