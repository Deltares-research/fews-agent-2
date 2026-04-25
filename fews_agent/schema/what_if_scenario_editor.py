"""WhatIfScenarioEditor.xml — region config for the scenario editor UI.

The XSD nests editorFilter recursively, with leaves of type
ScenarioTemplate that further branch into basic /
workflowSpecific forms. Each form can carry a configFileSelection,
variableTransformation, extendedLocationSpecification,
locationSelection, or areaSelection — each itself a deep tree.

Strategy: top-level structure (root attributes, permission strings,
defaults, the recursive editorFilter list) is typed; the leaves
beneath ``scenarioTemplates`` are passed through as ``dict[str, Any]``
to keep the schema tractable.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .common import FewsModel


class EditorMapDisplay(FewsModel):
    """XSD EditorMapDisplayComplexType — geoMap reference + content.

    GeoMap content is broad; pass through.
    """

    geoMap: dict[str, Any] = Field(default_factory=dict)
    geoMapId: str


class EditorDisplayDefaults(FewsModel):
    """XSD EditorDisplayDefaultsComplexType."""

    mapDefaults: EditorMapDisplay | None = None


class EditorFilter(FewsModel):
    """XSD EditorFilterComplexType — recursive folder grouping with
    optional terminal scenarioTemplates.

    The scenarioTemplates child wraps the choice between basic and
    workflowSpecific templates. Both forms are deep, so the entire
    scenarioTemplates payload is a dict pass-through.
    """

    editorFilter: list["EditorFilter"] = Field(default_factory=list)
    scenarioTemplates: dict[str, Any] | None = None
    name: str
    description: str | None = None


class WhatIfScenarioEditor(FewsModel):
    """Root of WhatIfScenarioEditor.xml."""

    editScenarioPermission: str | None = None
    createScenarioPermission: str | None = None
    deleteScenarioPermission: str | None = None
    persistScenarioPermission: str | None = None
    runScenarioPermission: str | None = None
    defaults: list[EditorDisplayDefaults] = Field(min_length=1)
    editorFilters: list[EditorFilter] = Field(min_length=1)
    title: str
    description: str | None = None
    deploymentMethod: Literal["direct", "viaManualForecast"]


EditorFilter.model_rebuild()
