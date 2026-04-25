"""UserGroups.xml — user group registry referenced by Permissions."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel
from .ids import UserGroupId


class UserRef(FewsModel):
    """User reference inside a group. XML: `<user id="None"/>`."""

    id: str


class UserGroup(FewsModel):
    # Attrs
    id: UserGroupId
    name: str | None = None
    # Members are an XSD choice (unbounded) between userGroup ref,
    # user ref, and systemUserGroup (AD group) — all simple id strings.
    userGroup: list[str] = Field(default_factory=list)
    user: list[UserRef] = Field(default_factory=list)
    systemUserGroup: list[str] = Field(default_factory=list)


class UserGroups(FewsModel):
    """Root of UserGroups.xml."""

    userGroup: list[UserGroup] = Field(min_length=1)
