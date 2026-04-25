"""Mc.xml — Master Controller configuration root.

XSD MCComplexType has ~14 optional top-level slots (mcId, name,
databaseIntId, logging, jvmOption[], adminInterface, taskRunDispatcher,
synch, azure[], fssGroups, workflowMappings, whatIfScenarios, tasks,
eventActions, eventActionMappings). Most have deep sub-trees (FssGroups,
WhatIfScenarios, Tasks, EventActions defined in cross-XSDs). The typed
surface here covers the simple scalar/list slots; the deep configuration
slots use ``dict[str, Any]`` passthrough.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel


class Mc(FewsModel):
    """Root of Mc.xml (``<mc>``)."""

    mcId: str | None = None
    name: str | None = None
    databaseIntId: str | None = None
    logging: dict[str, Any] | None = None
    jvmOption: list[str] = Field(default_factory=list)
    adminInterface: dict[str, Any] | None = None
    taskRunDispatcher: dict[str, Any] | None = None
    synch: dict[str, Any] | None = None
    # ``azure`` is repeatable (one block per FSS group).
    azure: list[dict[str, Any]] = Field(default_factory=list)
    fssGroups: dict[str, Any] | None = None
    workflowMappings: dict[str, Any] | None = None
    whatIfScenarios: dict[str, Any] | None = None
    tasks: dict[str, Any] | None = None
    eventActions: dict[str, Any] | None = None
    eventActionMappings: dict[str, Any] | None = None
