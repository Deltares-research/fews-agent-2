"""Permissions.xml — FEWS system permissions keyed to user groups.

Each permission lists the userGroups that hold it. In XML the userGroup
reference is a self-closing element with an `id` attribute
(`<userGroup id="InVisible"/>`), so we model it as a tiny object rather
than a bare string.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel
from .ids import PermissionId, UserGroupId


class UserGroupRef(FewsModel):
    """Reference to a userGroup declared in UserGroups.xml."""

    id: UserGroupId


class Permission(FewsModel):
    id: PermissionId
    # Since 2024.01 — global property reference can gate availability
    # per clientConfig.xml or environment. XSD default is true.
    enabled: bool | None = None
    userGroup: list[UserGroupRef] = Field(default_factory=list)


class Permissions(FewsModel):
    """Root of Permissions.xml."""

    permission: list[Permission] = Field(min_length=1)
