"""Security.xml — actions + roles with granted action refs per role."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel


class SecurityAction(FewsModel):
    id: str
    description: str | None = None


class SecurityActions(FewsModel):
    """`<actions>` wrapper around `<action>` elements."""

    action: list[SecurityAction] = Field(min_length=1)


class SecurityGrants(FewsModel):
    actionId: list[str] = Field(min_length=1)


class SecurityRole(FewsModel):
    # XSD restricts id to these four role names.
    id: Literal["Viewer", "Forecaster", "ConfigManager", "SystemManager"]
    description: str | None = None
    buttonText: str | None = None
    userGroups: str | None = None
    noPasswordRequired: bool | None = None
    password: str
    grants: SecurityGrants


class SecurityRoles(FewsModel):
    """`<roles>` wrapper around `<role>` elements."""

    role: list[SecurityRole] = Field(min_length=1)


class Security(FewsModel):
    """Root of Security.xml."""

    actions: SecurityActions
    roles: SecurityRoles
