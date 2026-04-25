"""ConfigUpdateModule.xml — picks up config files dropped into an import dir."""
from __future__ import annotations

from .common import FewsModel


class ConfigUpdateImport(FewsModel):
    importDir: str
    backupDir: str
    failedDir: str
    skipUpdateOnValidationFailure: bool | None = None


class ConfigUpdateModule(FewsModel):
    """Root of ConfigUpdateModule.xml."""

    mapLayerImport: ConfigUpdateImport
