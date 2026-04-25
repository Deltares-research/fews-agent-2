"""ConfigUpdateScriptConfig.xml — inactive config-update script settings.

Marked ``INACTIVE`` in the XSD. Controls where FEWS imports SQL-style
config-update scripts from and where to move succeeded/failed files.
"""
from __future__ import annotations

from .common import FewsModel


class ImportMapLayerFilesSettings(FewsModel):
    failedDirectory: str | None = None
    backupDirectory: str | None = None


class ConfigUpdateScriptConfig(FewsModel):
    versionIncrement: float
    scriptDirectory: str
    failedDirectory: str | None = None
    backupDirectory: str | None = None
    importMapLayerFilesSettings: ImportMapLayerFilesSettings | None = None
