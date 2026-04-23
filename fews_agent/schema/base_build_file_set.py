"""BaseBuildFileSet.xml — manifest of files in a base-build zip, with
per-file sha1 hashes for integrity verification."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class BaseBuildFile(FewsModel):
    relativePath: str
    hash: str


class BaseBuildFileSet(FewsModel):
    """Root of BaseBuildFileSet.xml."""

    file: list[BaseBuildFile] = Field(min_length=1)
