"""Archives.xml — registry of archive endpoints used by FEWS.

XSD ArchivesComplexType has a flat sequence of mostly-scalar fields plus
a few deep sub-trees (externalCFCompliantNetCdfStorage[], seamlessWaterML2[],
seamlessFewsWebService[], archiveDatabase, customExportFolders,
exportWithoutMetadataFile, archiveUploadTask, seamlessIntegrationTimeSeries
group). The shallow scalars are typed; the deep ones pass through as
``dict[str, Any]``.

``catalogueUrl`` is the only required element — everything else is
``minOccurs="0"``.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel


class Archives(FewsModel):
    """Root of Archives.xml (``<archives>``)."""

    enabled: bool | None = None
    catalogueUrl: str
    openDapUrl: str | None = None
    fileServerUrl: str | None = None
    elasticSearchUrl: str | None = None
    dataFolder: str | None = None
    createFewsConfigFromArchive: bool | None = None
    fewsWebServicesAlwaysImportsDataFromExternalDataSource: bool | None = None
    areaLocationAttributeFunction: list[str] = Field(default_factory=list)
    # SeamlessIntegrationTimeSeriesGroup is a choice between a list of
    # filters or a single boolean. Modelled as two parallel optional
    # passthrough surfaces — caller supplies one or neither (XSD allows
    # the group to be absent via minOccurs="0").
    seamlessIntegrationTimeSeries: list[dict[str, Any]] = Field(
        default_factory=list
    )
    notUsedForSeamlessIntegration: bool | None = None
    externalCFCompliantNetCdfStorage: list[dict[str, Any]] = Field(
        default_factory=list
    )
    archiveDatabase: dict[str, Any] | None = None
    seamlessWaterML2: list[dict[str, Any]] = Field(default_factory=list)
    seamlessFewsWebService: list[dict[str, Any]] = Field(default_factory=list)
    maxConnectionRetryCount: int | None = None
    seamlessIntegrationIsOptional: bool | None = None
    locationGroupAttributeId: str | None = None
    uploadEditedDataToOpenArchive: bool | None = None
    customExportFolders: dict[str, Any] | None = None
    exportWithoutMetadataFile: dict[str, Any] | None = None
    archiveUploadTask: dict[str, Any] | None = None
