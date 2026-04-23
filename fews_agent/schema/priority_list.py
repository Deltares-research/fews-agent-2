"""Priorities.xml — priority lists for storage basin structures.

XSD root element is <priorities> (plural). Each priorityList entry is
keyed by an int id; each priority maps a structure state to an index.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel


class Priority(FewsModel):
    structureId: str
    stateId: int
    priorityIndex: int
    priorityStatus: Literal["active", "required", "not_available"] | None = None


class PriorityList(FewsModel):
    id: int
    priority: list[Priority] = Field(min_length=1)


class Priorities(FewsModel):
    """Root of Priorities.xml."""

    priorityList: list[PriorityList] = Field(min_length=1)
