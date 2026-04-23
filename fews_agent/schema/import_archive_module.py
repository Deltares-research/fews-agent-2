"""ImportArchiveModule.xml — pulls forecast/observed/... data from a
Delft-FEWS archive back into the system.

XSD root uses `<choice maxOccurs="unbounded">` over 9 import-kind
elements (simulated, observed, messages, etc.). We model each kind as
its own typed list and emit them in a stable order. Two of the kinds
share a common 2-field shape (timeSeriesSetIdMap + importFolder) —
reused via ArchiveImportBasic.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel


class ArchiveImportBasic(FewsModel):
    """Shared shape for most import kinds: optional idMap + folder."""

    timeSeriesSetIdMap: str | None = None
    importFolder: str


class ArchiveImportMessages(FewsModel):
    importFolder: str


class ImportArchiveModule(FewsModel):
    """Root of ImportArchiveModule.xml.

    At least one import-kind entry must be supplied (XSD outer choice).
    """

    importSimulated: list[ArchiveImportBasic] = Field(default_factory=list)
    importSimulatedHistorical: list[ArchiveImportBasic] = Field(default_factory=list)
    importObserved: list[ArchiveImportBasic] = Field(default_factory=list)
    importMessages: list[ArchiveImportMessages] = Field(default_factory=list)
    importExternalForecast: list[ArchiveImportBasic] = Field(default_factory=list)
    importHistoricalEvents: list[ArchiveImportBasic] = Field(default_factory=list)
    importRatingCurves: list[ArchiveImportBasic] = Field(default_factory=list)
    importEditedData: list[ArchiveImportBasic] = Field(default_factory=list)
    importRequestedDataSets: list[ArchiveImportBasic] = Field(default_factory=list)
    # Trailing logErrorsAsWarnings / logErrorsAsWarningsToFileOnly — XSD
    # wraps them in a choice (0..1). We expose both; at most one should
    # be set in practice.
    logErrorsAsWarnings: bool | None = None
    logErrorsAsWarningsToFileOnly: bool | None = None

    @model_validator(mode="after")
    def _at_least_one_import(self) -> ImportArchiveModule:
        if not any([
            self.importSimulated, self.importSimulatedHistorical,
            self.importObserved, self.importMessages,
            self.importExternalForecast, self.importHistoricalEvents,
            self.importRatingCurves, self.importEditedData,
            self.importRequestedDataSets,
        ]):
            raise ValueError(
                "importArchiveModule: supply at least one import-kind entry"
            )
        if self.logErrorsAsWarnings is not None and self.logErrorsAsWarningsToFileOnly is not None:
            raise ValueError(
                "importArchiveModule: set at most one of logErrorsAsWarnings "
                "or logErrorsAsWarningsToFileOnly (XSD choice)"
            )
        return self
