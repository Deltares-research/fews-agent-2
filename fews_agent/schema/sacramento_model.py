"""SacramentoModel.xml — config for the Sacramento hydrological model adapter.

Self-contained: AdapterGeneral / AdapterActivity are defined locally in
sacramentoModel.xsd (not a shared type). AdapterMappingComplexType is
pulled from sharedTypes."""
from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from .common import FewsModel


class AdapterMapping(FewsModel):
    parameterId: str
    locationId: str
    column: int


class SacramentoAdapterActivity(FewsModel):
    dateFormat: str
    input: list[str] = Field(min_length=1)
    output: list[str] = Field(min_length=1)
    mapping: list[AdapterMapping] = Field(min_length=1)


class SacramentoAdapterGeneral(FewsModel):
    workDir: str
    importDir: str
    exportDir: str
    stateFile: str
    diagnosticFile: str
    missingValue: Decimal


class SacramentoAdapterActivities(FewsModel):
    preAdapterActivities: list[SacramentoAdapterActivity] = Field(default_factory=list)
    postAdapterActivities: list[SacramentoAdapterActivity] = Field(default_factory=list)


class SacramentoModel(FewsModel):
    """Root of SacramentoModel.xml."""

    general: SacramentoAdapterGeneral
    activities: SacramentoAdapterActivities
