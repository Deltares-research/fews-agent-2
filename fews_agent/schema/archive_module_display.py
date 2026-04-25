"""ArchiveModuleDisplay.xml — Archive catalogue configuration.

Self-contained aside from the existing TimeStep / RelativeViewPeriod
compounds.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel, RelativeViewPeriod, TimeStep


SearchDataType = Literal[
    "forecasterNotes",
    "ratingcurves",
    "observed",
    "simulated",
    "modifiers",
    "reports",
    "simulated time series",
    "simulated historical",
    "states",
    "externalForecast",
    "config",
    "snapshot",
    "products",
]


class ArchiveThresholdIds(FewsModel):
    levelThresholdId: list[str] = Field(min_length=1)


class DownloadFolders(FewsModel):
    downloadFolderObserved: str
    downloadFolderSimulated: str
    downloadFolderSimulatedHistorical: str | None = None
    downloadFolderExternalForecasts: str
    downloadFolderRatingCurves: str
    downloadFolderHistoricalEvents: str
    downloadFolderForecasterNotes: str
    downloadFolderConfiguration: str
    downloadFolderEventAttachments: str
    downloadFolderSnapShots: str | None = None
    downloadFolderProducts: str | None = None


class SearchDataTypes(FewsModel):
    type: list[SearchDataType] = Field(min_length=1)


class DataSearchProperty(FewsModel):
    propertyId: str
    displayName: str | None = None


class ArchiveModuleDisplay(FewsModel):
    levelThresholds: ArchiveThresholdIds | None = None
    defaultHistoricalEventTimeStep: TimeStep | None = None
    workFolder: str
    createEventPermission: str | None = None
    deleteEventPermission: str | None = None
    uploadNewDataPermission: str | None = None
    disableDataDownloadAtOperatorClient: bool | None = None
    downloadFolders: DownloadFolders
    archiveImportWorkflowId: str | None = None
    fssImport: bool | None = None
    searchDataTypes: SearchDataTypes | None = None
    hideDownloadDataSetsTab: bool | None = None
    hideCreateEventTab: bool | None = None
    hideSearchEventTab: bool | None = None
    hideArchiveDatabaseTab: bool | None = None
    hideArchiveUploadTab: bool | None = None
    archiveUploadIdMapId: str | None = None
    initialSearchTimePeriod: RelativeViewPeriod | None = None
    dataSearchProperty: list[DataSearchProperty] = Field(default_factory=list, max_length=2)
