"""LDAPLoginModule.xml — authentication via LDAP directory."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel


class LDAPConnection(FewsModel):
    hostName: str
    port: int | None = None
    ldapVersion: Literal["LDAP_V3"] | None = None
    dn: str
    password: str


class LDAPSearch(FewsModel):
    searchBase: str
    searchScope: Literal["SCOPE_BASE", "SCOPE_ONE", "SCOPE_SUB"] | None = None
    searchFilter: str | None = None
    attributeName: str


class LDAPLoginModule(FewsModel):
    """Root of LDAPLoginModule.xml."""

    connection: list[LDAPConnection] = Field(min_length=1)
    userSearch: LDAPSearch
    groupSearch: LDAPSearch
