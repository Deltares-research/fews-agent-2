"""LDAPLoginModule generator."""
from __future__ import annotations

from fews_agent.schema import LDAPLoginModule

from .base import render


def generate(model: LDAPLoginModule) -> str:
    return render("root/ldap_login_module.xml.j2", model)
