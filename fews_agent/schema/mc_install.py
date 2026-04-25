"""McInstall.xml — CommandLineInterface install descriptor.

XSD root: ``systems`` (SystemsComplexType). Each ``system`` contains a
``database`` (Oracle | PostgreSQL | SqlServer choice + databaseServer)
and an ``mc`` (huge MCComplexType — full Master Controller config).

Both ``database`` and ``mc`` subtrees are deeply nested with FEWS-
internal types (Oracle/Postgres/SQL Server tablespace shapes, MC
logging, taskRunDispatcher, eventActions, ...). Per CLAUDE.md
"``dict[str, Any]`` for subtrees deeper than 3 nesting levels", we
model each as a pass-through dict.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel


class McInstallSystem(FewsModel):
    """One <system> entry — required database + mc subtrees."""

    database: dict[str, Any]
    mc: dict[str, Any]


class McInstall(FewsModel):
    """Root of McInstall.xml — root element name is ``systems``."""

    system: list[McInstallSystem] = Field(min_length=1)
