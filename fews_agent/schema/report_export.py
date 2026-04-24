"""ReportExport.xml — export settings for report pages.

Sections, all optional:
  - reportExportTelegramPhoto (Telegram.org bot integration)
  - currentForecastReports (per-forecast export)
  - exportForecastReports (deprecated)
  - exportSystemStatusReports (most-recent system reports)

Root attribute `version` is fixed="1.0" per XSD.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel, TimeZone


class TelegramSendPhoto(FewsModel):
    reportTelegramFile: str
    reportTelegramCaption: str | None = None


class ReportExportTelegramPhoto(FewsModel):
    telegramBotToken: str
    telegramChatId: str
    telegramSendPhoto: list[TelegramSendPhoto] = Field(min_length=1)


class GenerateImage(FewsModel):
    format: str | None = None
    options: str | None = None


class CurrentForecastReports(FewsModel):
    currentForcastSubDir: str
    zipReports: bool | None = None
    dateTimeFormat: str | None = None
    exportTimeZone: TimeZone | None = None
    prefix: str | None = None
    numberCurrentForecasts: int | None = None
    excludeModuleInstanceId: list[str] = Field(default_factory=list)
    includeModuleInstanceId: list[str] = Field(default_factory=list)
    incremental: bool | None = None
    generatePdf: bool | None = None
    generateImage: GenerateImage | None = None

    @model_validator(mode="after")
    def _exclude_xor_include(self) -> CurrentForecastReports:
        if self.excludeModuleInstanceId and self.includeModuleInstanceId:
            raise ValueError(
                "currentForecastReports: use excludeModuleInstanceId or "
                "includeModuleInstanceId, not both"
            )
        return self


class ExportForecastReports(FewsModel):
    """Deprecated since 2011.01. Still schema-valid."""

    exportForcastSubDir: str
    numberForecastsToExport: int
    excludeModuleInstanceId: list[str] = Field(default_factory=list)
    includeModuleInstanceId: list[str] = Field(default_factory=list)


class ExportSystemStatusReports(FewsModel):
    """XSD choice: directory-branch (sub-dir + optional zipReports /
    dateTimeFormat / prefix) XOR zip-file-branch (exportSystemStatusZipFile)."""

    exportSystemStatusSubDir: str | None = None
    zipReports: bool | None = None
    dateTimeFormat: str | None = None
    prefix: str | None = None
    exportSystemStatusZipFile: str | None = None
    includeModuleInstanceId: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_branch(self) -> ExportSystemStatusReports:
        dir_branch = self.exportSystemStatusSubDir is not None
        zip_branch = self.exportSystemStatusZipFile is not None
        if dir_branch and zip_branch:
            raise ValueError(
                "exportSystemStatusReports: pick either exportSystemStatusSubDir "
                "or exportSystemStatusZipFile, not both"
            )
        if not dir_branch and not zip_branch:
            raise ValueError(
                "exportSystemStatusReports: supply exportSystemStatusSubDir or "
                "exportSystemStatusZipFile"
            )
        if zip_branch and (
            self.zipReports is not None
            or self.dateTimeFormat is not None
            or self.prefix is not None
        ):
            raise ValueError(
                "exportSystemStatusReports: zipReports/dateTimeFormat/prefix are "
                "only valid with exportSystemStatusSubDir"
            )
        return self


class ReportExport(FewsModel):
    version: str = "1.0"
    reportExportRootDir: str
    reportExportTelegramPhoto: ReportExportTelegramPhoto | None = None
    currentForecastReports: CurrentForecastReports | None = None
    exportForecastReports: ExportForecastReports | None = None
    exportSystemStatusReports: ExportSystemStatusReports | None = None
    dataFeedId: str | None = None
