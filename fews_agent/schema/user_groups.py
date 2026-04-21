"""UserGroups.xml — user group registry referenced by Permissions."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel
from .ids import UserGroupId


class UserRef(FewsModel):
    """User reference inside a group. XML: `<user id="None"/>`."""

    id: str


class UserGroup(FewsModel):
    id: UserGroupId
    user: list[UserRef] = Field(default_factory=list)


class UserGroups(FewsModel):
    """Root of UserGroups.xml."""

    userGroup: list[UserGroup] = Field(min_length=1)
